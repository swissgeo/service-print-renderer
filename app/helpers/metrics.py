"""OpenTelemetry metrics for the print renderer.

The instruments are created at import time from the global meter provider set up
in app.helpers.otel. Until it is configured (or when metrics are disabled) they
resolve to no-op proxies, so the ``record_*`` helpers are always safe to call.

``scope.version`` (METRICS_SCHEMA_VERSION) is the version of the metric schema
emitted under this scope -- bump it on any schema change (semver).
"""

from opentelemetry import metrics
from opentelemetry.semconv._incubating.attributes import messaging_attributes
from opentelemetry.semconv._incubating.metrics.messaging_metrics import (
    create_messaging_client_consumed_messages,
    create_messaging_process_duration,
)
from opentelemetry.semconv.attributes import error_attributes

METRICS_SCHEMA_VERSION = "1.0.0"
meter = metrics.get_meter(__name__, METRICS_SCHEMA_VERSION)

MAX_RETRIES_EXCEEDED = "max-retries-exceeded"
JOB_FAILED = "failed"

# Emits "messaging.client.consumed.messages" ({message}) and
# "messaging.process.duration" (s). Name, unit and description come from the
# semantic conventions rather than from literals repeated here, so a spec update
# arrives with the next dependency bump.
_consumed_messages = create_messaging_client_consumed_messages(meter)
_process_duration = create_messaging_process_duration(meter)

# messaging.operation.name names the domain operation, not the SQS API call:
# one message on this queue is one print job.
_MESSAGING_ATTRIBUTES = {
    messaging_attributes.MESSAGING_OPERATION_NAME: "print",
    messaging_attributes.MESSAGING_SYSTEM: messaging_attributes.MessagingSystemValues.AWS_SQS.value,
}


def record_message_consumed(error_type: str | None = None) -> None:
    """Count one print job the renderer finished with.

    Recorded once per job, at its terminal outcome: a successful render, or a
    permanent failure once the SQS redrive policy is exhausted -- the latter
    carrying ``error.type``. The redeliveries in between are not counted.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _consumed_messages.add(1, attributes)


def record_process_duration(seconds: float, error_type: str | None = None) -> None:
    """Record how long the renderer spent processing one message.

    Recorded once per processing attempt, so a redelivered job adds a sample per
    attempt and ``_sum`` accumulates its total processing time. A failed attempt
    carries ``error.type``. Excludes the time the message waited in the queue.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _process_duration.record(seconds, attributes)
