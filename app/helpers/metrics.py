"""OpenTelemetry metrics for the print renderer.

The instruments are created at import time from the global meter provider set up
in app.helpers.otel. Until it is configured (or when metrics are disabled) they
resolve to no-op proxies, so the ``record_*`` helpers are always safe to call.

``scope.version`` (METRICS_SCHEMA_VERSION) is the version of the metric schema
emitted under this scope -- bump it on any schema change (semver).
"""

from enum import StrEnum
from typing import Literal

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
    JOB_PROCESSING_RETRIED = "job-processing-retried"
    # One processing attempt failed on the last try, no retries left.
    JOB_PROCESSING_FAILED = "job-processing-failed"
    # The job failed for good, having exhausted the SQS redrive policy.
    JOB_PROCESSING_RETRIES_EXCEEDED = "job-processing-retries-exceeded"


# Emits "messaging.client.consumed.messages" ({message}) and
# "messaging.process.duration" (s). Name, unit and description come from the
# semantic conventions rather than from literals repeated here, so a spec update
# arrives with the next dependency bump.
_consumed_messages = create_messaging_client_consumed_messages(meter)
_process_duration = create_messaging_process_duration(meter)

# Emits "swissgeo.messaging.queue.duration" (s).
# Custom because the messaging semantic conventions have no instrument for the
# time a message sat in the queue: messaging.client.operation.duration measures
# the receive *call*, not the wait. swissgeo.messaging.* is the ADD's form for a
# metric that fits an OTEL namespace but is not defined by the spec.
_queue_duration = meter.create_histogram(
    name="swissgeo.messaging.queue.duration",
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


def record_message_consumed(
    error_type: Literal[ErrorType.JOB_PROCESSING_RETRIES_EXCEEDED] | None = None,
) -> None:
    """Count one print job the renderer finished with.

    Recorded once per job, at its terminal outcome: a successful render, or a
    permanent failure once the SQS redrive policy is exhausted -- the latter
    carrying ``error.type = job-processing-retries-exceeded``. The redeliveries
    in between are not counted.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _consumed_messages.add(1, attributes)


def record_process_duration(
    seconds: float,
    error_type: Literal[ErrorType.JOB_PROCESSING_RETRIED, ErrorType.JOB_PROCESSING_FAILED]
    | None = None,
) -> None:
    """Record how long the renderer spent processing one message.

    Recorded once per processing attempt, so a redelivered job adds a sample per
    attempt and ``_sum`` accumulates its total processing time. Excludes the
    queue wait. A failed attempt carries ``error.type``:
    ``job-processing-retried`` when it will be retried, ``job-processing-failed``
    on the final attempt.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _process_duration.record(seconds, attributes)


def record_queue_duration(
    seconds: float,
    error_type: Literal[ErrorType.JOB_PROCESSING_RETRIED] | None = None,
) -> None:
    """Record how long a message had been in the SQS queue when received.

    First delivery (no ``error.type``): the clean queue wait. A redelivery
    carries ``error.type = job-processing-retried``; ``SentTimestamp`` is not
    reset on redelivery, so the value then spans the whole retry cycle (the
    failed attempt(s) plus their visibility-timeout waits) -- the message's total
    age, kept as a separate series from the first-pickup wait.
    """
    attributes = _MESSAGING_ATTRIBUTES
    if error_type is not None:
        attributes = attributes | {error_attributes.ERROR_TYPE: error_type}

    _queue_duration.record(seconds, attributes)
