"""OpenTelemetry metrics for the print renderer.

The instruments are created at import time from the global meter provider set up
in app.helpers.otel. Until it is configured (or when metrics are disabled) they
resolve to no-op proxies, so the ``record_*`` helpers are always safe to call.

``scope.version`` (METRICS_SCHEMA_VERSION) is the version of the metric schema
emitted under this scope -- bump it on any schema change (semver).
"""

from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.semconv._incubating.attributes import messaging_attributes
from opentelemetry.semconv._incubating.metrics.messaging_metrics import (
    create_messaging_client_consumed_messages,
    create_messaging_process_duration,
)
from opentelemetry.semconv.attributes import error_attributes

METRICS_SCHEMA_VERSION = "1.0.0"
meter = metrics.get_meter(__name__, METRICS_SCHEMA_VERSION)


class ErrorType(StrEnum):
    """Allowed values for the ``error.type`` metric attribute.

    A closed set keeps the attribute low-cardinality -- an unbounded string here
    would fan each instrument out into a new time series per distinct value. The
    values are mutually exclusive on any one sample.
    """

    # One processing attempt failed; the job will be redelivered for another try.
    PROCESSING_RETRIED = "processing-retried"
    # One processing attempt failed on the last try, no retries left.
    PROCESSING_FAILED = "processing-failed"
    # The job failed for good, having exhausted the SQS redrive policy.
    PROCESSING_RETRIES_EXCEEDED = "processing-retries-exceeded"
    # A render phase ran into TIMEOUT_LOADING_WEB_PAGE.
    RENDER_TIMEOUT = "render-timeout"
    # A render phase failed for any other reason.
    RENDER_ERROR = "render-error"


class RenderPhase(StrEnum):
    """Allowed values for the ``swissgeo.render.phase`` metric attribute.

    The phases are sequential and together make up the render, so they are
    kept apart: the page not being delivered (portal) and the map never becoming
    ready (layer and tile backends) are different faults with different owners.
    """

    NAVIGATE = "navigate"
    MAP_READY = "map_ready"
    PDF = "pdf"


# Emits "messaging.client.consumed.messages" ({message}) and
# "messaging.process.duration" (s). Name, unit and description come from the
# semantic conventions rather than from literals repeated here, so a spec update
# arrives with the next dependency bump.
_consumed_messages = create_messaging_client_consumed_messages(meter)
_process_duration = create_messaging_process_duration(meter)

# Explicit bucket boundaries (s), applied as SDK views in app.helpers.otel. The SDK
# default (0, 5, 10, 25, 50, ...) is sized for milliseconds, and the semconv
# advisory for messaging.process.duration stops at 10s, below the 30s
# TIMEOUT_LOADING_WEB_PAGE a slow render runs into. The Elastic ingest places
# every sample at its bucket's midpoint, so the buckets are dense where renders
# and timeouts land.
PROCESS_DURATION_BUCKETS = (
    0.5, 1, 2, 3, 4, 5, 6, 8, 10, 12.5, 15, 20, 25, 30, 35, 40, 50, 60, 90, 120,
)  # fmt: skip
# A redelivery's queue duration spans SQS_VISIBILITY_TIMEOUT waits, hence the
# long tail.
QUEUE_DURATION_BUCKETS = (
    0.1, 0.25, 0.5, 1, 2.5, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300, 600, 900, 1800, 3600,
)  # fmt: skip
# A single phase is capped by the 30s TIMEOUT_LOADING_WEB_PAGE; a timeout lands in
# (30, 35]. PDF generation takes well under a second, hence the fine low end.
RENDER_DURATION_BUCKETS = (
    0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 35, 45, 60,
)  # fmt: skip

# Emits "swissgeo.service_print.render.duration" (s).
# Custom because no OTEL namespace covers rendering a page in a browser.
RENDER_DURATION = "swissgeo.service_print.render.duration"
_render_duration = meter.create_histogram(
    name=RENDER_DURATION,
    unit="s",
    description="Time one phase of rendering a print job in headless Chrome took.",
)

# Emits "swissgeo.messaging.queue.duration" (s).
# Custom because the messaging semantic conventions have no instrument for the
# time a message sat in the queue: messaging.client.operation.duration measures
# the receive *call*, not the wait. swissgeo.messaging.* is the ADD's form for a
# metric that fits an OTEL namespace but is not defined by the spec.
QUEUE_DURATION = "swissgeo.messaging.queue.duration"
_queue_duration = meter.create_histogram(
    name=QUEUE_DURATION,
    unit="s",
    description=(
        "Time from a message being sent to the SQS queue to it being received by "
        "the renderer, from SentTimestamp."
    ),
)

# messaging.operation.name names the domain operation, not the SQS API call:
# one message on this queue is one print job.
_MESSAGING_ATTRIBUTES = {
    messaging_attributes.MESSAGING_OPERATION_NAME: "print",
    messaging_attributes.MESSAGING_SYSTEM: messaging_attributes.MessagingSystemValues.AWS_SQS.value,
}


def record_message_consumed(error_type: ErrorType | None = None) -> None:
    """Count one print job the renderer finished with.

    Recorded once per job, at its terminal outcome: a successful render, or a
    permanent failure once the SQS redrive policy is exhausted -- the latter
    carrying ``error.type = processing-retries-exceeded``. The redeliveries
    in between are not counted.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _consumed_messages.add(1, attributes)


def record_process_duration(seconds: float, error_type: ErrorType | None = None) -> None:
    """Record how long the renderer spent processing one message.

    Recorded once per processing attempt, so a redelivered job adds a sample per
    attempt and ``_sum`` accumulates its total processing time. Excludes the
    queue wait. A failed attempt carries ``error.type``:
    ``processing-retried`` when it will be retried, ``processing-failed``
    on the final attempt.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _process_duration.record(seconds, attributes)


def record_queue_duration(seconds: float, error_type: ErrorType | None = None) -> None:
    """Record how long a message had been in the SQS queue when received.

    First delivery (no ``error.type``): the clean queue wait. A redelivery
    carries ``error.type = processing-retried``; ``SentTimestamp`` is not
    reset on redelivery, so the value then spans the whole retry cycle (the
    failed attempt(s) plus their visibility-timeout waits) -- the message's total
    age, kept as a separate series from the first-pickup wait.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _queue_duration.record(seconds, attributes)


def record_render_duration(
    phase: RenderPhase, seconds: float, error_type: ErrorType | None = None
) -> None:
    """Record how long one render phase took.

    Recorded once per phase and processing attempt, so a failed attempt only has
    samples up to the phase that failed. That phase carries ``error.type``:
    ``render-timeout`` when it ran into TIMEOUT_LOADING_WEB_PAGE, otherwise
    ``render-error``.
    """
    attributes: dict[str, str] = {"swissgeo.render.phase": phase}
    if error_type is not None:
        attributes[error_attributes.ERROR_TYPE] = error_type

    _render_duration.record(seconds, attributes)
