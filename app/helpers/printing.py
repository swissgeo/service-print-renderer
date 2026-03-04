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

    from playwright.sync_api import BrowserContext, Page, Playwright

from app.config.settings import (
    BROWSER_LAUNCH_ARGS,
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
_CHROME_USER_DATA_DIR = "/tmp/user_data"  # nosec B108  # noqa: S108


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
    """Manages a headless Chrome instance for PDF rendering via Playwright."""

    _playwright: Playwright | None
    _browser: BrowserContext | None
    _page: Page | None

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self._playwright = None
        self._browser = None
        self._page = None

        self._paper_size: str = str(payload["format"]).lower()
        self._denom = int(payload["scale"])
        self._resolution = int(payload.get("resolution", 96)) or 96
        self._dpi = self._resolution  # may be overridden below

        z_exact = self._denom_to_z_lv95(self._denom)
        self._z = z_exact

        if ROUND_UP_TO_NEXT_Z_INT:
            z_ceil = math.ceil(z_exact)
            self._set_dpi_for_overzoom(self._denom, z_ceil)
            self._z = z_ceil

        if GO_ONE_Z_FURTHER:
            self._z = self._z + 1
            self._set_dpi_for_overzoom(self._denom, int(self._z))

        self._scale = 96 / self._dpi
        orientation_code = "L" if payload["orientation"] == "landscape" else "P"
        self._print_config = f"{self._paper_size}_{orientation_code},{self._dpi}".upper()

        if payload["orientation"] == "portrait":
            self._width, self._height = PAPER_SIZES[self._paper_size]
        else:
            self._height, self._width = PAPER_SIZES[self._paper_size]

    def __enter__(self) -> Self:
        logger.info(
            "Launching Chrome (format=%s, orientation=%s, dpi=%d, z=%.3f)",
            self._paper_size,
            self._payload["orientation"],
            self._dpi,
            self._z,
        )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch_persistent_context(
            headless=True,
            channel="chrome",
            args=BROWSER_LAUNCH_ARGS,
            executable_path=_CHROME_EXECUTABLE,
            user_data_dir=_CHROME_USER_DATA_DIR,
            viewport={"width": self._width, "height": self._height},
            device_scale_factor=self._resolution / 96,
        )
        self._page = self._browser.new_page()
        self._page.set_default_timeout(TIMEOUT_LOADING_WEB_PAGE)
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

    def _denom_to_z_lv95(self, denom: int) -> float:
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

    def _set_dpi_for_overzoom(self, denom: int, z: int) -> None:
        """Recalculate DPI when rendering at a higher zoom level than requested."""
        self._dpi = round(96 * (denom / MATRIX_LV95[z]))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_url(self) -> str:
        """Construct the full webmapviewer URL for the current job."""
        query = _remove_z_param(str(self._payload["query"]))
        view = str(self._payload.get("view", "print_map"))

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

        return f"{base_url}?{query}&printConfig={self._print_config}&z={self._z}"

    def navigate_to_url(self, url: str) -> None:
        """Navigate to the webmapviewer URL and wait until the map is ready."""
        if not self._page:
            msg = "Browser page is not initialised"
            raise RuntimeError(msg)

        logger.info("Navigating to %s", url)
        self._page.goto(url)

        # The webmapviewer fires a 'gaMapReady' window message when fully loaded.
        self._page.evaluate(
            """
            new Promise(resolve => {
                window.addEventListener("message", event => {
                    if (event.data.type === 'gaMapReady') resolve(event.data);
                });
            })
            """
        )
        self._page.wait_for_load_state("networkidle")
        logger.info("Page loaded")

    def save_page_as_pdf(self, output_path: Path) -> None:
        """Render the current page to a PDF file."""
        if not self._page:
            msg = "Browser page is not initialised"
            raise RuntimeError(msg)

        is_landscape = self._payload["orientation"] == "landscape"
        page_format = str(self._payload["format"]).upper()

        logger.info("Saving PDF to %s", output_path)
        self._page.emulate_media(media="print")
        self._page.pdf(
            path=str(output_path),
            format=page_format,
            landscape=is_landscape,
            print_background=True,
            scale=self._scale,
        )
        logger.info("PDF saved successfully")

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


def render_to_pdf(payload: dict, output_path: Path) -> None:
    """Render a print job payload to a PDF at *output_path*.

    Args:
        payload: The job payload dict (format, orientation, scale, resolution,
                 view, query).
        output_path: Destination path for the generated PDF.

    Raises:
        RuntimeError: If Playwright encounters an unrecoverable error.
    """
    # Validate URL config before launching Chrome so we don't waste resources
    # on a job that will always fail.
    view = str(payload.get("view", "print_map"))
    if view == "print_legend":
        if not VIEWER_URL_LEGEND:
            msg = "VIEWER_URL_LEGEND is not configured — set it in your environment"
            raise ValueError(msg)
    elif VECTOR_TILES:
        if not VIEWER_URL_MAP:
            msg = "VIEWER_URL_MAP is not configured — set it in your environment"
            raise ValueError(msg)
    elif not VIEWER_URL_MAP_RASTER:
        msg = "VIEWER_URL_MAP_RASTER is not configured — set it in your environment"
        raise ValueError(msg)

    try:
        with ChromeBrowserManager(payload) as manager, _timed("render_to_pdf total"):
            with _timed("build_url"):
                url = manager.build_url()
            with _timed("navigate_to_url"):
                manager.navigate_to_url(url)
            with _timed("save_page_as_pdf"):
                manager.save_page_as_pdf(output_path)
    except Error as exc:
        logger.exception("Playwright error during rendering")
        msg = "PDF rendering failed"
        raise RuntimeError(msg) from exc
