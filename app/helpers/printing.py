"""Playwright-based PDF rendering via headless Chrome."""

import contextlib
import logging
import math
import time
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode

from playwright.sync_api import Error, sync_playwright

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from types import TracebackType
    from typing import Self

    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from app.config.settings import (
    BROWSER_LAUNCH_ARGS,
    BROWSER_NAVIGATION_RETRIES,
    GO_ONE_Z_FURTHER,
    MATRIX_LV95,
    PAPER_SIZES,
    ROUND_UP_TO_NEXT_Z_INT,
    TIMEOUT_LOADING_WEB_PAGE,
    VECTOR_TILES,
    VIEWER_URL_LEGEND,
    VIEWER_URL_MAP,
    VIEWER_URL_MAP_RASTER,
)

logger = logging.getLogger(__name__)

_CHROME_EXECUTABLE = "/usr/bin/google-chrome"


@contextlib.contextmanager
def _timed(label: str) -> Generator:
    """Log the elapsed wall-clock time of the wrapped block at DEBUG level."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.debug("%s took %.3fs", label, elapsed)


def _remove_z_param(query: str) -> str:
    """Strip the z= parameter from a URL query string.

    The zoom level is recalculated from the scale denominator, so any
    z already present in the client query must be removed first.
    """
    params = parse_qsl(query, keep_blank_values=True)
    return urlencode([(k, v) for k, v in params if k != "z"])


class ChromeBrowserManager:
    """Manages a long-lived headless Chrome instance for PDF rendering via Playwright.

    Chrome is launched once on ``__enter__`` and kept alive for the lifetime of
    the context manager.  Each call to ``render_to_pdf`` opens a fresh
    ``BrowserContext`` (with the job-specific viewport and scale) and closes it
    when the PDF has been written, so jobs are fully isolated while the
    expensive Chrome process is reused.
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> Self:
        logger.info("Launching Chrome")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            channel="chrome",
            args=BROWSER_LAUNCH_ARGS,
            executable_path=_CHROME_EXECUTABLE,
        )
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _denom_to_z_lv95(denom: int) -> float:
        """Interpolate a (fractional) zoom level from a scale denominator."""
        z_keys = list(MATRIX_LV95.keys())

        n_unbound = next((i for i, v in enumerate(MATRIX_LV95.values()) if v < denom), -1)

        n = max(0, n_unbound - 1) if n_unbound >= 0 else len(z_keys) - 2
        z_n = z_keys[n]
        z_np1 = z_keys[n + 1]
        delta_z = math.log(denom / MATRIX_LV95[z_n]) / math.log(
            MATRIX_LV95[z_np1] / MATRIX_LV95[z_n]
        )
        return round(z_n + delta_z * (z_np1 - z_n), 3)

    def _resolve_job_params(self, payload: dict) -> dict:
        """Derive all rendering parameters from the job payload."""
        paper_size = str(payload["format"]).lower()
        denom = int(payload["scale"])
        resolution = int(payload.get("resolution", 96)) or 96
        dpi = resolution

        z_exact = self._denom_to_z_lv95(denom)
        z = z_exact

        if ROUND_UP_TO_NEXT_Z_INT:
            z_ceil = math.ceil(z_exact)
            dpi = round(96 * (denom / MATRIX_LV95[z_ceil]))
            z = z_ceil

        if GO_ONE_Z_FURTHER:
            z = z + 1
            dpi = round(96 * (denom / MATRIX_LV95[int(z)]))

        scale = 96 / dpi
        orientation_code = "L" if payload["orientation"] == "landscape" else "P"
        print_config = f"{paper_size}_{orientation_code},{dpi}".upper()

        if payload["orientation"] == "portrait":
            width, height = PAPER_SIZES[paper_size]
        else:
            height, width = PAPER_SIZES[paper_size]

        return {
            "paper_size": paper_size,
            "dpi": dpi,
            "z": z,
            "scale": scale,
            "print_config": print_config,
            "width": width,
            "height": height,
            "resolution": resolution,
        }

    def _build_url(self, payload: dict, params: dict) -> str:
        """Construct the full webmapviewer URL for the current job."""
        query = _remove_z_param(str(payload["query"]))
        view = str(payload.get("view", "print_map"))

        if view == "print_legend":
            base_url = VIEWER_URL_LEGEND
            env_var = "VIEWER_URL_LEGEND"
        elif VECTOR_TILES:
            base_url = VIEWER_URL_MAP
            env_var = "VIEWER_URL_MAP"
        else:
            base_url = VIEWER_URL_MAP_RASTER
            env_var = "VIEWER_URL_MAP_RASTER"

        if not base_url:
            msg = f"{env_var} is not configured — set it in your environment"
            raise ValueError(msg)

        return f"{base_url}?{query}&printConfig={params['print_config']}&z={params['z']}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render_to_pdf(self, payload: dict, output_path: Path) -> None:
        """Render a print job to PDF, reusing the long-lived Chrome process.

        A fresh ``BrowserContext`` is created for each job (to apply the
        job-specific viewport and device scale) and closed when done, so
        successive jobs do not share any browser state.

        Args:
            payload: The job payload dict (format, orientation, scale,
                     resolution, view, query).
            output_path: Destination path for the generated PDF.

        Raises:
            RuntimeError: If the browser is not initialised or Playwright
                          encounters an unrecoverable error.
        """
        if not self._browser:
            msg = "Browser is not initialised — use ChromeBrowserManager as a context manager"
            raise RuntimeError(msg)

        params = self._resolve_job_params(payload)
        logger.info(
            "Rendering job (format=%s, orientation=%s, dpi=%d, z=%.3f)",
            params["paper_size"],
            payload["orientation"],
            params["dpi"],
            params["z"],
        )

        context: BrowserContext = self._browser.new_context(
            viewport={"width": params["width"], "height": params["height"]},
            device_scale_factor=params["resolution"] / 96,
        )
        try:
            page: Page = context.new_page()
            page.set_default_timeout(TIMEOUT_LOADING_WEB_PAGE)

            with _timed("build_url"):
                url = self._build_url(payload, params)

            logger.info("Navigating to %s", url)
            with _timed("navigate_to_url"):
                for attempt in range(BROWSER_NAVIGATION_RETRIES):
                    try:
                        page.goto(url)
                        break
                    except Error as exc:
                        if (
                            "ERR_NETWORK_CHANGED" in str(exc)
                            and attempt < BROWSER_NAVIGATION_RETRIES - 1
                        ):
                            logger.warning(
                                "ERR_NETWORK_CHANGED, retrying navigation (attempt %d)",
                                attempt + 1,
                            )
                            time.sleep(0.5)
                        else:
                            raise
                page.evaluate(
                    """
                    new Promise(resolve => {
                        window.addEventListener("message", event => {
                            if (event.data.type === 'gaMapReady') resolve(event.data);
                        });
                    })
                    """
                )
                page.wait_for_load_state("networkidle")
            logger.info("Page loaded")

            is_landscape = payload["orientation"] == "landscape"
            page_format = str(payload["format"]).upper()
            logger.info("Saving PDF to %s", output_path)
            with _timed("save_page_as_pdf"):
                page.emulate_media(media="print")
                page.pdf(
                    path=str(output_path),
                    format=page_format,
                    landscape=is_landscape,
                    print_background=True,
                    scale=params["scale"],
                )
            logger.info("PDF saved successfully")
        except Error as exc:
            logger.exception("Playwright error during rendering")
            msg = "PDF rendering failed"
            raise RuntimeError(msg) from exc
        finally:
            context.close()

    def close(self) -> None:
        """Close the browser and stop the Playwright context."""
        try:
            if self._browser:
                self._browser.close()
        except Exception:  # noqa: BLE001
            logger.warning("Error closing browser, ignoring", exc_info=True)
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            logger.warning("Error stopping Playwright, ignoring", exc_info=True)
