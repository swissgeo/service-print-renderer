"""OpenTelemetry metrics for the print renderer worker.

The instruments below are created at import time from the global meter provider.
When metrics are disabled (``initialize_otel`` did not register a MeterProvider)
they resolve to no-op proxies, so the ``record_*`` helpers are always safe to
call regardless of configuration.

``scope.version`` (METRICS_SCHEMA_VERSION) is the version of the metric schema
emitted under this scope - bump it on any schema change (semver: MAJOR for a
breaking rename/type/unit change, MINOR for additive, PATCH for docs only).
"""

from opentelemetry import metrics

METRICS_SCHEMA_VERSION = "1.0.0"
meter = metrics.get_meter(__name__, METRICS_SCHEMA_VERSION)

# One counter with an ``outcome`` attribute rather than five separate counters:
# keeps the job lifecycle events queryable together and low-cardinality. The
# ``started - success - error - dropped`` difference approximates in-flight jobs.
# Outcomes: "started", "success", "error", "dropped" here; "created" is emitted by
# service-print-api (scope app.core.metrics) under this same instrument name, so
# name, unit and description must stay identical across the two scopes.
_jobs = meter.create_counter(
    "swissgeo.service_print.jobs",
    unit="{job}",
    description="Print jobs, labelled by lifecycle outcome",
)

_processing_duration = meter.create_histogram(
    "swissgeo.service_print.job.processing.duration",
    unit="s",
    description="Time spent rendering and uploading a job, excluding queue wait",
)

_wait_duration = meter.create_histogram(
    "swissgeo.service_print.job.wait.duration",
    unit="s",
    description="Time a job spent waiting in the SQS queue before first pickup",
)

_print_duration = meter.create_histogram(
    "swissgeo.service_print.print.duration",
    unit="s",
    description="End-to-end time from print request creation to job completion",
)


def record_job_started() -> None:
    """Count a job entering processing (recorded once per job, on first pickup)."""
    _jobs.add(1, {"outcome": "started"})


def record_job_succeeded() -> None:
    """Count a job that finished successfully (PDF uploaded, DynamoDB updated)."""
    _jobs.add(1, {"outcome": "success"})


def record_job_failed() -> None:
    """Count a job that failed permanently (marked 'error' on the final attempt)."""
    _jobs.add(1, {"outcome": "error"})


def record_job_dropped() -> None:
    """Count a job dropped from the queue into the DLQ after max retries."""
    _jobs.add(1, {"outcome": "dropped"})


def record_processing_duration(seconds: float) -> None:
    """Record the render + upload duration of a successful job, in seconds."""
    _processing_duration.record(seconds)


def record_waiting_time(seconds: float) -> None:
    """Record how long a job waited in the queue before first pickup, in seconds."""
    _wait_duration.record(seconds)


def record_print_duration(seconds: float) -> None:
    """Record the request-to-completion duration of a job, in seconds."""
    _print_duration.record(seconds)
