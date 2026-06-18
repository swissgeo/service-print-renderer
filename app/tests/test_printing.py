from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.helpers.printing import _TEMPORARY_Z, ChromeBrowserManager

_PAYLOAD = {
    "print_format": "a4",
    "print_orientation": "portrait",
    "print_resolution": 96,
    "print_scale": 50000,
    "state_id": "mipNBAzN1lvPUl9V",
    "print_legend": True,
    "print_grid": False,
    "print_lang": "de",
}


def test_enter_launches_browser():
    """__enter__ must start Playwright and launch Chromium."""
    mock_playwright = MagicMock()
    mock_browser = MagicMock()
    mock_playwright.chromium.launch.return_value = mock_browser

    with patch("app.helpers.printing.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.start.return_value = mock_playwright

        mgr = ChromeBrowserManager()
        result = mgr.__enter__()

    assert mgr._playwright is mock_playwright
    assert mgr._browser is mock_browser
    assert result is mgr


def test_build_url_path_includes_lang_and_print(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    url = ChromeBrowserManager()._build_url(_PAYLOAD)
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.dev.sgdi.tech"
    assert parsed.path == "/de/print"


def test_build_url_drops_lang_segment_when_absent(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    payload = {k: v for k, v in _PAYLOAD.items() if k != "print_lang"}
    assert urlparse(ChromeBrowserManager()._build_url(payload)).path == "/print"


def test_build_url_drops_lang_segment_when_empty(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    url = ChromeBrowserManager()._build_url({**_PAYLOAD, "print_lang": ""})
    assert urlparse(url).path == "/print"


def test_build_url_carries_state_and_print_params(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    qs = parse_qs(urlparse(ChromeBrowserManager()._build_url(_PAYLOAD)).query)
    assert qs["state"] == ["mipNBAzN1lvPUl9V"]
    assert qs["print_format"] == ["a4"]
    assert qs["print_resolution"] == ["96"]
    assert qs["print_orientation"] == ["portrait"]
    assert qs["print_scale"] == ["50000"]


def test_build_url_sends_temporary_fixed_z(monkeypatch):
    # TODO: remove with _TEMPORARY_Z once the web-portal derives zoom from print_scale.
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    qs = parse_qs(urlparse(ChromeBrowserManager()._build_url(_PAYLOAD)).query)
    assert qs["z"] == [str(_TEMPORARY_Z)]


def test_build_url_state_id_renamed_to_state(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    qs = parse_qs(urlparse(ChromeBrowserManager()._build_url(_PAYLOAD)).query)
    assert "state_id" not in qs


def test_build_url_booleans_lowercased(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    qs = parse_qs(urlparse(ChromeBrowserManager()._build_url(_PAYLOAD)).query)
    assert qs["print_legend"] == ["true"]
    assert qs["print_grid"] == ["false"]


def test_build_url_excludes_print_lang_from_query(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "https://www.dev.sgdi.tech/?")
    qs = parse_qs(urlparse(ChromeBrowserManager()._build_url(_PAYLOAD)).query)
    assert "print_lang" not in qs


def test_build_url_raises_missing_portal_url(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.PORTAL_URL", "")
    with pytest.raises(ValueError, match="PORTAL_URL"):
        ChromeBrowserManager()._build_url(_PAYLOAD)


def test_render_to_pdf_raises_without_browser(tmp_path):
    mgr = ChromeBrowserManager()
    with pytest.raises(RuntimeError, match="not initialised"):
        mgr.render_to_pdf(_PAYLOAD, tmp_path / "4a80ad23a0d62b4102.pdf")


def test_close_suppresses_browser_exception():
    mgr = ChromeBrowserManager()
    mgr._browser = MagicMock()
    mgr._browser.close.side_effect = Exception("browser boom")
    mgr.close()  # must not raise


def test_close_suppresses_playwright_exception():
    mgr = ChromeBrowserManager()
    mgr._playwright = MagicMock()
    mgr._playwright.stop.side_effect = Exception("playwright boom")
    mgr.close()  # must not raise


def test_close_noop_when_nothing_started():
    mgr = ChromeBrowserManager()
    mgr.close()  # must not raise


def test_close_calls_browser_and_playwright():
    mgr = ChromeBrowserManager()
    mgr._browser = MagicMock()
    mgr._playwright = MagicMock()
    mgr.close()
    mgr._browser.close.assert_called_once()
    mgr._playwright.stop.assert_called_once()
