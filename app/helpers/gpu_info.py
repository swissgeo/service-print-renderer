"""GPU information fetcher via headless Chrome and WebGL."""

import logging

from playwright.sync_api import Error, sync_playwright

from app.config.settings import BROWSER_LAUNCH_ARGS

logger = logging.getLogger(__name__)

_CHROME_EXECUTABLE = "/usr/bin/google-chrome"
_CHROME_USER_DATA_DIR = "/tmp/user_data"  # nosec B108  # noqa: S108

_GPU_INFO_SCRIPT = """
[document.createElement('canvas')].map((cc) => {
    const hwContext = document.createElement('canvas').getContext('webgl', {
        failIfMajorPerformanceCaveat: true
    });
    const gl = cc.getContext('webgl');
    let rendererName = 'WebGL Context Unavailable';
    if (gl) {
        try {
            const dbgRenderInfo = gl.getExtension('WEBGL_debug_renderer_info');
            if (dbgRenderInfo) {
                rendererName = gl.getParameter(dbgRenderInfo.UNMASKED_RENDERER_WEBGL);
            } else {
                rendererName = gl.getParameter(gl.RENDERER);
            }
        } catch (error) {
            rendererName = `Error retrieving info: ${error.message}`;
        }
    }
    return { hw: hwContext !== null, name: rendererName };
})[0]
"""


def log_gpu_info() -> None:
    """Launch a headless Chrome instance and log GPU/WebGL information."""
    logger.info("Fetching GPU info via headless Chrome...")
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch_persistent_context(
            headless=True,
            channel="chrome",
            args=BROWSER_LAUNCH_ARGS,
            executable_path=_CHROME_EXECUTABLE,
            user_data_dir=_CHROME_USER_DATA_DIR,
        )
        page = browser.new_page()
        gpu_data = page.evaluate(_GPU_INFO_SCRIPT)
        browser.close()
        playwright.stop()
        logger.info("Hardware acceleration available: %s", gpu_data.get("hw"))
        logger.info("GPU renderer name: %s", gpu_data.get("name"))
    except Error:
        logger.exception("Failed to fetch GPU info")
