from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import MATRIX_LV95
from app.helpers.printing import ChromeBrowserManager, _remove_z_param

_PAYLOAD = {
    "format": "a4",
    "orientation": "portrait",
    "scale": 50000,
    "resolution": 96,
    "view": "print_map",
    "query": "layers=ch.swisstopo.pixelkarte-farbe&topic=ech",
}

# Minimal params dict as produced by _resolve_job_params
_PARAMS = {"print_config": "A4_P,96", "z": 6.9}


def test_remove_z_param_strips_z():
    result = _remove_z_param("layers=ch.swisstopo.pixelkarte-farbe&z=12&topic=ech")
    assert "z=12" not in result
    assert "layers=ch.swisstopo.pixelkarte-farbe" in result
    assert "topic=ech" in result


def test_remove_z_param_no_z_unchanged():
    query = "layers=ch.swisstopo.pixelkarte-farbe&topic=ech"
    assert _remove_z_param(query) == query


def test_remove_z_param_only_z_returns_empty():
    assert _remove_z_param("z=5") == ""


def test_remove_z_param_empty_string():
    assert _remove_z_param("") == ""


def test_remove_z_param_z_not_reintroduced():
    result = _remove_z_param("z=25&layers=ch.swisstopo.pixelkarte-farbe&z=3")
    assert "z=25" not in result
    assert "z=3" not in result


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


def test_resolve_job_params_portrait_width_less_than_height():
    result = ChromeBrowserManager()._resolve_job_params(_PAYLOAD)
    assert result["width"] < result["height"]


def test_resolve_job_params_landscape_width_greater_than_height():
    payload = {**_PAYLOAD, "orientation": "landscape"}
    result = ChromeBrowserManager()._resolve_job_params(payload)
    assert result["width"] > result["height"]


def test_resolve_job_params_print_config_a4_portrait():
    result = ChromeBrowserManager()._resolve_job_params(_PAYLOAD)
    assert result["print_config"].startswith("A4_P,")


def test_resolve_job_params_print_config_a4_landscape():
    payload = {**_PAYLOAD, "orientation": "landscape"}
    result = ChromeBrowserManager()._resolve_job_params(payload)
    assert result["print_config"].startswith("A4_L,")


def test_resolve_job_params_print_config_a3():
    payload = {**_PAYLOAD, "format": "a3"}
    result = ChromeBrowserManager()._resolve_job_params(payload)
    assert result["print_config"].startswith("A3_P,")


def test_resolve_job_params_resolution_default_when_absent():
    payload = {k: v for k, v in _PAYLOAD.items() if k != "resolution"}
    result = ChromeBrowserManager()._resolve_job_params(payload)
    assert result["resolution"] == 96


def test_resolve_job_params_zero_resolution_falls_back_to_96():
    result = ChromeBrowserManager()._resolve_job_params({**_PAYLOAD, "resolution": 0})
    assert result["resolution"] == 96


def test_resolve_job_params_scale_used_as_denom():
    result = ChromeBrowserManager()._resolve_job_params(_PAYLOAD)
    # z should be computed from the 500000 denominator and fall within the matrix range
    z_keys = list(MATRIX_LV95.keys())
    assert z_keys[0] <= result["z"] <= z_keys[-1]


def test_denom_to_z_exact_zoom_level():
    z_target = 7
    denom = MATRIX_LV95[z_target]
    assert ChromeBrowserManager._denom_to_z_lv95(denom) == float(z_target)


def test_denom_to_z_result_within_matrix_range():
    # 500000 falls between z=2 (944882) and z=3 (377953) → precomputed expected
    assert ChromeBrowserManager._denom_to_z_lv95(500000) == 2.695


def test_denom_to_z_between_two_levels_is_fractional():
    # midpoint between z=4 (188976) and z=5 (75591) → precomputed expected
    assert ChromeBrowserManager._denom_to_z_lv95(132283) == 4.389


def test_build_url_raster(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_MAP_RASTER", "http://map-raster")
    url = ChromeBrowserManager()._build_url(_PAYLOAD, _PARAMS)
    assert url == (
        "http://map-raster?layers=ch.swisstopo.pixelkarte-farbe&topic=ech&printConfig=A4_P,96&z=6.9"
    )


def test_build_url_vector(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_MAP", "http://map-vector")
    url = ChromeBrowserManager()._build_url({**_PAYLOAD, "view": "print_vec_map"}, _PARAMS)
    assert url == (
        "http://map-vector?layers=ch.swisstopo.pixelkarte-farbe&topic=ech&printConfig=A4_P,96&z=6.9"
    )


def test_build_url_legend(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_LEGEND", "http://legend")
    url = ChromeBrowserManager()._build_url({**_PAYLOAD, "view": "print_legend"}, _PARAMS)
    assert url == (
        "http://legend?layers=ch.swisstopo.pixelkarte-farbe&topic=ech&printConfig=A4_P,96&z=6.9"
    )


def test_build_url_strips_original_z_from_query(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_MAP_RASTER", "http://map")
    payload = {**_PAYLOAD, "query": "layers=ch.swisstopo.pixelkarte-farbe&z=25&topic=ech"}
    url = ChromeBrowserManager()._build_url(payload, _PARAMS)
    assert "z=25" not in url


def test_build_url_raises_missing_raster_url(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_MAP_RASTER", "")
    with pytest.raises(ValueError, match="VIEWER_URL_MAP_RASTER"):
        ChromeBrowserManager()._build_url(_PAYLOAD, _PARAMS)


def test_build_url_raises_missing_vector_url(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_MAP", "")
    payload = {**_PAYLOAD, "view": "print_vec_map"}
    with pytest.raises(ValueError, match="VIEWER_URL_MAP"):
        ChromeBrowserManager()._build_url(payload, _PARAMS)


def test_build_url_raises_missing_legend_url(monkeypatch):
    monkeypatch.setattr("app.helpers.printing.VIEWER_URL_LEGEND", "")
    payload = {**_PAYLOAD, "view": "print_legend"}
    with pytest.raises(ValueError, match="VIEWER_URL_LEGEND"):
        ChromeBrowserManager()._build_url(payload, _PARAMS)


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
