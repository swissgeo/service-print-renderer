"""Playwright-based PDF rendering via headless Chrome."""

import contextlib
import logging
import time
from collections.abc import Generator
from pathlib import Path
from types import TracebackType
from typing import Self
from urllib.parse import urlencode

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error,
    Page,
    Playwright,
    Response,
    sync_playwright,
)

from app.config.settings import (
    BROWSER_LAUNCH_ARGS,
    BROWSER_NAVIGATION_RETRIES,
    PORTAL_URL,
    TIMEOUT_LOADING_WEB_PAGE,
)

logger = logging.getLogger(__name__)


class RenderingError(RuntimeError):
    """A single job could not be rendered to PDF.

    Signals a job-level failure (the web-portal errored, or Playwright failed
    while rendering) that the worker can act on by letting SQS redrive the
    message. It is deliberately distinct from configuration/programming errors
    (e.g. unset ``PORTAL_URL`` or an uninitialised browser), which should crash
    the worker instead of being treated as a bad job.
    """


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


def _format_query_value(value: object) -> str:
    """Render a payload value for use in the web-portal query string.

    Booleans are lowercased to ``true``/``false`` so the web-portal receives
    JS-style flags rather than Python's capitalised ``True``/``False``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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

    def _build_url(self, payload: dict) -> str:
        """Construct the full web-portal URL for the current job.

        The URL has the shape ``<base>/<print_lang>/print?<query>`` where the
        query carries the ``state`` id and every ``print_*`` payload key
        (except ``print_lang``, which is part of the path). All values are
        forwarded to the web-portal verbatim — no zoom/resolution math happens
        here.
        """
        if not PORTAL_URL:
            raise ValueError("PORTAL_URL is not configured — set it in your environment")

        base = PORTAL_URL.rstrip("?/")
        path = f"{base}/{payload['print_lang']}/print"

        query_items: list[tuple[str, str]] = [
            ("state", str(payload["state_id"])),
        ]
        query_items += [
            (key, _format_query_value(value))
            for key, value in payload.items()
            if key.startswith("print_") and key != "print_lang"
        ]

        return f"{path}?{urlencode(query_items)}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def render_to_pdf(self, payload: dict, output_path: Path) -> None:
        """Render a print job to PDF, reusing the long-lived Chrome process.

        A fresh ``BrowserContext`` is created for each job and closed when
        done, so successive jobs do not share any browser state. The browser
        runs at a device pixel ratio of 1; the web-portal is responsible for all
        layout, zoom and resolution.

        Args:
            payload: The job payload dict (print_format, print_orientation,
                     print_scale, print_resolution, print_lang, state_id,
                     print_legend, print_grid).
            output_path: Destination path for the generated PDF.

        Raises:
            RuntimeError: If the browser is not initialised (a programming error).
            RenderingError: If the web-portal errors or Playwright fails to
                            render the job (a job-level failure).
        """
        if not self._browser:
            raise RuntimeError(
                "Browser is not initialised — use ChromeBrowserManager as a context manager"
            )

        logger.info(
            "Rendering job (format=%s, orientation=%s)",
            payload["print_format"],
            payload["print_orientation"],
        )

        context: BrowserContext = self._browser.new_context()
        try:
            page: Page = context.new_page()
            page.set_default_timeout(TIMEOUT_LOADING_WEB_PAGE)

            with _timed("build_url"):
                url = self._build_url(payload)

            page.add_init_script("""
                window.__GA_MAP_READY__ = false;
                window.addEventListener("message", event => {
                    if (event.data?.type === "gaMapReady") {
                        window.__GA_MAP_READY__ = true;
                    }
                });
            """)

            logger.info("Navigating to %s", url)
            with _timed("navigate_to_url"):
                response: Response | None = None
                for attempt in range(BROWSER_NAVIGATION_RETRIES):
                    try:
                        response = page.goto(url)
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
                # goto() does not raise on HTTP error statuses, and gaMapReady never
                # fires when the portal errors - fail fast instead of waiting for the
                # gaMapReady timeout below.
                if response is not None and not response.ok:
                    raise RenderingError(f"web-portal returned HTTP {response.status} for {url}")
                page.wait_for_function(
                    "() => window.__GA_MAP_READY__ === true",
                    timeout=TIMEOUT_LOADING_WEB_PAGE,
                )
            logger.info("Page loaded")

            is_landscape = payload["print_orientation"] == "landscape"
            page_format = str(payload["print_format"]).upper()
            # Chrome's PDF renderer assumes 96 CSS px per inch; scale the output so
            # the requested dpi maps back to that baseline.
            dpi = float(payload["print_resolution"])
            scale = 96 / dpi
            logger.info("Saving PDF to %s", output_path)
            with _timed("save_page_as_pdf"):
                page.emulate_media(media="print")
                page.pdf(
                    path=str(output_path),
                    format=page_format,
                    landscape=is_landscape,
                    print_background=True,
                    scale=scale,
                )
            logger.info("PDF saved successfully")
        except Error as exc:
            logger.exception("Playwright error during rendering")
            msg = "PDF rendering failed"
            raise RenderingError(msg) from exc
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
