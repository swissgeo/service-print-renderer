import functools
import logging
from collections.abc import Callable
from os import getenv
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.trace import SpanKind

from app.helpers.utils import init_logging, strtobool

_RESOURCE = Resource.create({"service.name": "service-print"})

# Set by _setup_logger_provider(), read by get_otel_handler() when the logging
# config resolves the ``otel`` handler. None when OTLP log export is not enabled.
_log_provider: LoggerProvider | None = None


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


def initialize_otel() -> tuple[TracerProvider | None, LoggerProvider | None]:
    """Initialize OpenTelemetry instrumentation, providers, and logging.

    Call once at worker startup. Performs, in order: botocore instrumentation,
    trace provider setup, OTLP log provider setup, and ``init_logging()`` (which
    must run last so the logging config's ``otel`` handler can resolve via
    ``get_otel_handler()``).

    Returns (trace_provider, logger_provider) so the caller can ``shutdown()``
    them on exit, flushing spans/logs still buffered in their batch processors.
    Either is None when the corresponding feature is disabled.

    Controlled by env vars:
    - OTEL_SDK_DISABLED: disables all instrumentation when true
    - OTEL_ENABLE_BOTOCORE: enables BotocoreInstrumentor when true
    - OTEL_ENABLE_OTLP_EXPORTER: export spans to the OTLP collector when true
      (default), otherwise print them to the console (no collector required);
      log export is disabled when false
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (default: http://localhost:4317)
    - OTEL_EXPORTER_OTLP_HEADERS: optional headers for the OTLP exporter
    - OTEL_EXPORTER_OTLP_INSECURE: use insecure (plaintext) connection when true
    """
    if not strtobool(getenv("OTEL_SDK_DISABLED", "false")) and strtobool(
        getenv("OTEL_ENABLE_BOTOCORE", "false")
    ):
        BotocoreInstrumentor().instrument()

    trace_provider = _setup_trace_provider()
    # The OTLP log provider must be set up before init_logging(): the logging
    # config's `otel` handler resolves via get_otel_handler(), which needs it.
    logger_provider = _setup_logger_provider()
    init_logging()

    return trace_provider, logger_provider


def shutdown_otel(
    trace_provider: TracerProvider | None,
    logger_provider: LoggerProvider | None,
) -> None:
    """Flush and shut down the OTEL providers returned by initialize_otel().

    Draining the batch processors flushes spans/logs still buffered before the
    process exits. Accepts None for either provider (when the feature was
    disabled) and ignores it.
    """
    if trace_provider is not None:
        trace_provider.shutdown()
    if logger_provider is not None:
        logger_provider.shutdown()


def _setup_trace_provider() -> TracerProvider | None:
    """Configure and register the trace provider.

    Returns the provider so the caller can ``shutdown()`` it on exit. This
    flushes the BatchSpanProcessor's buffered spans, which are otherwise lost
    when the process stops before the next batch tick. Returns None when the
    SDK is disabled.
    """
    if strtobool(getenv("OTEL_SDK_DISABLED", "false")):
        return None

    exporter: SpanExporter
    if strtobool(getenv("OTEL_ENABLE_OTLP_EXPORTER", "true")):
        exporter = OTLPSpanExporter(
            endpoint=getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317"),
            headers=getenv("OTEL_EXPORTER_OTLP_HEADERS"),
            insecure=strtobool(getenv("OTEL_EXPORTER_OTLP_INSECURE", "false")),
        )
    else:
        exporter = ConsoleSpanExporter()

    provider = TracerProvider(resource=_RESOURCE)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def _setup_logger_provider() -> LoggerProvider | None:
    """Configure and register an OTLP log provider for exporting logs to the collector.

    Returns the provider so the caller can ``shutdown()`` it on exit (flushing
    the BatchLogRecordProcessor). Returns None, and the ``otel`` logging handler
    is then unavailable, when the SDK is disabled or the OTLP exporter is turned
    off (``OTEL_ENABLE_OTLP_EXPORTER=false``).
    """
    global _log_provider  # noqa: PLW0603

    if strtobool(getenv("OTEL_SDK_DISABLED", "false")) or not strtobool(
        getenv("OTEL_ENABLE_OTLP_EXPORTER", "true")
    ):
        return None

    provider = LoggerProvider(resource=_RESOURCE)
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
    ``initialize_otel()`` must have run first (with OTLP export enabled),
    otherwise there is no provider to attach to.
    """
    if _log_provider is None:
        raise ValueError(
            "OTEL log provider is not available — call initialize_otel() before "
            "loading the logging config, and ensure OTEL_ENABLE_OTLP_EXPORTER is true"
        )
    return LoggingHandler(logger_provider=_log_provider)
