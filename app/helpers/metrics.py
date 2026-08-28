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
)
from opentelemetry.semconv.attributes import error_attributes

METRICS_SCHEMA_VERSION = "1.0.0"
meter = metrics.get_meter(__name__, METRICS_SCHEMA_VERSION)

MAX_RETRIES_EXCEEDED = "max-retries-exceeded"

# Emits "messaging.client.consumed.messages" ({message}).
# Name, unit and description come from the semantic conventions rather than from
# literals repeated here, so a spec update arrives with the next dependency bump.
_consumed_messages = create_messaging_client_consumed_messages(meter)

# messaging.operation.name names the domain operation, not the SQS API call:
# one message on this queue is one print job.
_CONSUME_ATTRIBUTES = {
    messaging_attributes.MESSAGING_OPERATION_NAME: "print",
    messaging_attributes.MESSAGING_SYSTEM: messaging_attributes.MessagingSystemValues.AWS_SQS.value,
}


def record_message_consumed(error_type: str | None = None) -> None:
    """Count one print job the renderer finished with.

    Recorded once per job, at its terminal outcome: a successful render, or a
    permanent failure once the SQS redrive policy is exhausted -- the latter
    carrying ``error.type``. The redeliveries in between are not counted.
    """
    attributes = _CONSUME_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _consumed_messages.add(1, attributes)
