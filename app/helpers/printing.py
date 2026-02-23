"""Playwright-based PDF rendering via headless Chrome."""

import logging
import math
import re
from typing import TYPE_CHECKING

from playwright.sync_api import Error, sync_playwright

if TYPE_CHECKING:
    from pathlib import Path

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


def _remove_z_param(query: str) -> str:
    """Strip the z= parameter from a URL query string.

    The zoom level is recalculated from the scale denominator, so any
    z already present in the client query must be removed first.
    """
    return re.sub(r"([?&])z=\d+(\.\d+)?", r"\1", query)


class ChromeBrowserManager:
    """Manages a headless Chrome instance for PDF rendering via Playwright."""

    _playwright: Playwright | None
    _browser: BrowserContext | None
    _page: Page | None

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        paper_size: str = str(payload["format"]).lower()

        self._playwright = sync_playwright().start()

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
        self._print_config = f"{paper_size}_{orientation_code},{self._dpi}".upper()

        if payload["orientation"] == "portrait":
            width, height = PAPER_SIZES[paper_size]
        else:
            height, width = PAPER_SIZES[paper_size]

        logger.info(
            "Launching Chrome (format=%s, orientation=%s, dpi=%d, z=%.3f)",
            paper_size,
            payload["orientation"],
            self._dpi,
            self._z,
        )
        self._browser = self._playwright.chromium.launch_persistent_context(
            headless=True,
            channel="chrome",
            args=BROWSER_LAUNCH_ARGS,
            executable_path=_CHROME_EXECUTABLE,
            user_data_dir=_CHROME_USER_DATA_DIR,
            viewport={"width": width, "height": height},
            device_scale_factor=self._resolution / 96,
        )
        self._page = self._browser.new_page()
        self._page.set_default_timeout(TIMEOUT_LOADING_WEB_PAGE)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _denom_to_z_lv95(self, denom: int) -> float:
        """Interpolate a (fractional) zoom level from a scale denominator."""
        z_keys = list(MATRIX_LV95.keys())
        values = list(MATRIX_LV95.values())

        try:
            n_unbound = next(i for i, v in enumerate(values) if v < denom)
        except StopIteration:
            n_unbound = -1

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

    manager = ChromeBrowserManager(payload)
    try:
        url = manager.build_url()
        manager.navigate_to_url(url)
        manager.save_page_as_pdf(output_path)
    except Error as exc:
        logger.exception("Playwright error during rendering")
        msg = "PDF rendering failed"
        raise RuntimeError(msg) from exc
    finally:
        manager.close()
