from unittest.mock import patch

import pytest

from app.helpers.otel import setup_trace_provider, strtobool

_OTLP_PATH = "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
_CONSOLE_PATH = "opentelemetry.sdk.trace.export.ConsoleSpanExporter"


@pytest.mark.parametrize("value", ["true", "1", "yes", "y", "on", "TRUE", " On "])
def test_strtobool_truthy(value):
    assert strtobool(value) is True


@pytest.mark.parametrize("value", ["false", "0", "no", "n", "off", "", "  "])
def test_strtobool_falsy(value):
    assert strtobool(value) is False


def test_strtobool_invalid_raises():
    with pytest.raises(ValueError, match="maybe"):
        strtobool("maybe")


def test_setup_trace_provider_noop_when_sdk_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    with patch("app.helpers.otel.trace.set_tracer_provider") as set_provider:
        setup_trace_provider()
    set_provider.assert_not_called()


def test_setup_trace_provider_uses_otlp_exporter_by_default(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.delenv("OTEL_ENABLE_OTLP_EXPORTER", raising=False)
    with (
        patch("app.helpers.otel.trace.set_tracer_provider"),
        patch(_OTLP_PATH) as otlp,
        patch(_CONSOLE_PATH) as console,
    ):
        setup_trace_provider()
    otlp.assert_called_once()
    console.assert_not_called()


def test_setup_trace_provider_uses_console_exporter_when_otlp_disabled(monkeypatch):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.setenv("OTEL_ENABLE_OTLP_EXPORTER", "false")
    with (
        patch("app.helpers.otel.trace.set_tracer_provider"),
        patch(_OTLP_PATH) as otlp,
        patch(_CONSOLE_PATH) as console,
    ):
        setup_trace_provider()
    console.assert_called_once()
    otlp.assert_not_called()
