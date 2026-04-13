import functools
from os import getenv
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from opentelemetry import trace
from opentelemetry.trace import SpanKind


def strtobool(value: str) -> bool:
    """Convert a string representation of truth to True or False.

    True values: 'y', 'yes', 'true', 'on', '1'.
    False values: 'n', 'no', 'false', 'off', '0', ''.

    Raises ValueError if value is anything else.
    """
    value = value.lower().strip()
    if value in ("true", "1", "yes", "y", "on"):
        return True
    if value in ("false", "0", "no", "n", "off", ""):
        return False
    raise ValueError(f"Cannot convert '{value}' to boolean")


def traced(span_name: str, kind: SpanKind = SpanKind.INTERNAL) -> Callable:
    """Decorator that wraps a function call in an OpenTelemetry span."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = trace.get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name, kind=kind):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def initialize() -> None:
    """Initialize OTEL instrumentation for logging and botocore.

    Should be called at worker startup. Controlled by env vars:
    - OTEL_SDK_DISABLED: disables all instrumentation when true
    - OTEL_ENABLE_LOGGING: enables LoggingInstrumentor when true
    - OTEL_ENABLE_BOTOCORE: enables BotocoreInstrumentor when true
    """
    if not strtobool(getenv("OTEL_SDK_DISABLED", "false")):
        if strtobool(getenv("OTEL_ENABLE_LOGGING", "false")):
            from opentelemetry.instrumentation.logging import LoggingInstrumentor

            LoggingInstrumentor().instrument()
        if strtobool(getenv("OTEL_ENABLE_BOTOCORE", "false")):
            from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

            BotocoreInstrumentor().instrument()


def setup_trace_provider() -> None:
    """Configure and register the OTLP trace provider.

    Controlled by env vars:
    - OTEL_SDK_DISABLED: disables all instrumentation when true
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: http://localhost:4318)
    - OTEL_EXPORTER_OTLP_HEADERS: optional headers for the exporter
    """
    if not strtobool(getenv("OTEL_SDK_DISABLED", "false")):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        span_processor = BatchSpanProcessor(OTLPSpanExporter())
        provider = TracerProvider(resource=Resource.create())
        provider.add_span_processor(span_processor)
        trace.set_tracer_provider(provider)
