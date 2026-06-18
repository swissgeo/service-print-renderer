import functools
import logging
from os import getenv
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.trace import TracerProvider

from opentelemetry import trace
from opentelemetry.trace import SpanKind

# Set by setup_logger_provider(), read by get_otel_handler() when the logging
# config resolves the ``otel`` handler. None when OTLP log export is not enabled.
_log_provider: LoggerProvider | None = None


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


def setup_trace_provider() -> TracerProvider | None:
    """Configure and register the trace provider.

    Returns the provider so the caller can ``shutdown()`` it on exit. This
    flushes the BatchSpanProcessor's buffered spans, which are otherwise lost
    when the process stops before the next batch tick. Returns None when the
    SDK is disabled.

    Controlled by env vars:
    - OTEL_SDK_DISABLED: disables all instrumentation when true
    - OTEL_ENABLE_OTLP_EXPORTER: export spans to the OTLP collector when true
      (default), otherwise print them to the console (no collector required)
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: http://localhost:4317)
    - OTEL_EXPORTER_OTLP_HEADERS: optional headers for the OTLP exporter
    - OTEL_EXPORTER_OTLP_INSECURE: use insecure (plaintext) connection when true
    """
    if strtobool(getenv("OTEL_SDK_DISABLED", "false")):
        return None

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

    exporter: SpanExporter
    if strtobool(getenv("OTEL_ENABLE_OTLP_EXPORTER", "true")):
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(
            endpoint=getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            headers=getenv("OTEL_EXPORTER_OTLP_HEADERS"),
            insecure=strtobool(getenv("OTEL_EXPORTER_OTLP_INSECURE", "false")),
        )
    else:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        exporter = ConsoleSpanExporter()

    provider = TracerProvider(resource=Resource.create())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def setup_logger_provider() -> LoggerProvider | None:
    """Configure and register an OTLP log provider for exporting logs to the collector.

    Must be called before the logging config is loaded so ``get_otel_handler()``
    can resolve the provider. Returns the provider so the caller can ``shutdown()``
    it on exit (flushing the BatchLogRecordProcessor). Returns None and the
    ``otel`` logging handler is then unavailable, when the SDK is disabled or the
    OTLP exporter is turned off (``OTEL_ENABLE_OTLP_EXPORTER=false``).

    Reads the same OTEL_EXPORTER_OTLP_* env vars as setup_trace_provider().
    """
    global _log_provider  # noqa: PLW0603

    if strtobool(getenv("OTEL_SDK_DISABLED", "false")) or not strtobool(
        getenv("OTEL_ENABLE_OTLP_EXPORTER", "true")
    ):
        return None

    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource

    provider = LoggerProvider(resource=Resource.create())
    provider.add_log_record_processor(
        BatchLogRecordProcessor(
            OTLPLogExporter(
                endpoint=getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
                headers=getenv("OTEL_EXPORTER_OTLP_HEADERS"),
                insecure=strtobool(getenv("OTEL_EXPORTER_OTLP_INSECURE", "false")),
            )
        )
    )
    set_logger_provider(provider)
    _log_provider = provider
    return provider


def get_otel_handler() -> logging.Handler:
    """Return an OTEL LoggingHandler bound to the configured log provider.

    Referenced from the logging config as ``(): app.helpers.otel.get_otel_handler``.
    ``setup_logger_provider()`` must have run first (with OTLP export enabled),
    otherwise there is no provider to attach to.
    """
    from opentelemetry.sdk._logs import LoggingHandler

    if _log_provider is None:
        raise ValueError(
            "OTEL log provider is not available — call setup_logger_provider() before "
            "loading the logging config, and ensure OTEL_ENABLE_OTLP_EXPORTER is true"
        )
    return LoggingHandler(logger_provider=_log_provider)
