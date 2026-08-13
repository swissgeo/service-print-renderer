"""
service-print-renderer worker

Polls the SQS queue filled by service-print-api, renders print jobs,
and updates the corresponding DynamoDB items with the result.

Entry point: python -m app.worker
"""

import argparse
import datetime
import logging
import signal
import sys
import tempfile
import time
from pathlib import Path

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from app.config.settings import (
    BROWSER_RECYCLE_AFTER_JOBS,
    LIVENESS_PROBE_FILE,
    SQS_DLQ_WAIT_TIME_SECONDS,
    SQS_MAX_RECEIVE_COUNT,
    SQS_WAIT_TIME_SECONDS,
    STARTUP_PROBE_FILE,
)
from app.helpers.dynamo_db import get_print_job, update_job_status
from app.helpers.gpu_info import log_gpu_info
from app.helpers.metrics import (
    record_job_failed,
    record_job_started,
    record_job_succeeded,
    record_processing_duration,
    record_total_duration,
    record_waiting_time,
)
from app.helpers.otel import initialize_otel, shutdown_otel, traced
from app.helpers.printing import ChromeBrowserManager, RenderingError
from app.helpers.s3 import upload_pdf
from app.helpers.sqs_queue import (
    delete_message,
    get_dlq_url,
    get_queue_url,
    parse_message_body,
    receive_messages,
)
from app.helpers.utils import get_iso_8601_timestamp, init_logging, touch_probe_file

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown  # noqa: PLW0603
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown = True


@traced("worker.process_job")
def process_job(job: dict, browser: ChromeBrowserManager) -> str:
    """
    Render a single print job and upload the result to S3.

    Args:
        job: The deserialized job dict (as stored in DynamoDB / sent to SQS
             by service-print-api).
        browser: The long-lived Chrome browser manager to render with.

    Returns:
        The S3 URL of the generated PDF.
    """
    job_id: str = job["job_id"]
    payload: dict = job["payload"]
    trace.get_current_span().set_attribute("job.id", job_id)
    logger.info("Processing job %s", job_id)

    update_job_status(
        job_id,
        "started",
        started_timestamp_iso_8601=get_iso_8601_timestamp(),
    )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        pdf_path = Path(tmp.name)
        browser.render_to_pdf(payload, pdf_path)
        return upload_pdf(job_id, pdf_path)


def _waiting_time_seconds(sent_timestamp: str | None) -> float | None:
    """Queue waiting time from the SQS SentTimestamp (epoch milliseconds).

    Returns None when the timestamp is absent or unparseable so the caller can
    skip recording the metric rather than emit a bogus value.
    """
    if not sent_timestamp:
        return None
    try:
        sent_epoch_s = int(sent_timestamp) / 1000
    except TypeError, ValueError:
        return None
    return max(0.0, time.time() - sent_epoch_s)


def _total_duration_seconds(job: dict) -> float | None:
    """End-to-end duration from the job's created timestamp to now.

    service-print-api stores ``created_timestamp_iso_8601`` on the job and sends
    it through SQS, so it is available here without an extra DynamoDB read.
    Returns None when it is missing or unparseable.
    """
    created_iso = job.get("created_timestamp_iso_8601")
    if not created_iso:
        return None
    try:
        created = datetime.datetime.fromisoformat(created_iso)
    except TypeError, ValueError:
        logger.debug("Job %s has unparseable created timestamp %r", job.get("job_id"), created_iso)
        return None
    return (datetime.datetime.now(datetime.UTC) - created).total_seconds()


@traced("worker.handle_message", kind=SpanKind.CONSUMER)
def handle_message(job_id: str, job: dict, message: dict, browser: ChromeBrowserManager) -> None:
    """
    Handle a single SQS message end-to-end: render the job, update its final
    status in DynamoDB and delete the message from the queue on success.
    On failure the message is not deleted — SQS will redeliver it until
    maxReceiveCount is reached, then move it to the DLQ automatically.
    DynamoDB is only updated to 'error' on the final attempt.
    """
    attributes = message.get("Attributes", {})
    receipt_handle: str = message["ReceiptHandle"]
    receive_count = int(attributes.get("ApproximateReceiveCount", 1))
    sent_timestamp: str | None = attributes.get("SentTimestamp")

    trace.get_current_span().set_attribute("job.id", job_id)
    # Prefixed: `messaging.*` is a reserved OTEL semconv namespace, already
    # populated on this span by botocore, and defines no receive-count attribute.
    trace.get_current_span().set_attribute("swissgeo.messaging.receive_count", receive_count)

    # Count the job as started and record its queue wait once, on first pickup,
    # so redeliveries don't inflate the counter or double-count the wait time.
    if receive_count <= 1:
        record_job_started()
        waiting_time = _waiting_time_seconds(sent_timestamp)
        if waiting_time is not None:
            record_waiting_time(waiting_time)

    processing_start = time.monotonic()
    try:
        pdf_location = process_job(job, browser)
        # The PDF lives at a deterministic key ({prefix}/{job_id}.pdf), so we only
        # record that the job finished — service-print-api derives the pdf URL from
        # the job_id once the status is 'finished'.
        update_job_status(
            job_id,
            "finished",
            finished_timestamp_iso_8601=get_iso_8601_timestamp(),
        )
        delete_message(receipt_handle, get_queue_url())
        logger.info("Job %s completed successfully (pdf uploaded to %s)", job_id, pdf_location)

        record_job_succeeded()
        record_processing_duration(time.monotonic() - processing_start)
        total_duration = _total_duration_seconds(job)
        if total_duration is not None:
            record_total_duration(total_duration)
    except (RenderingError, KeyError) as exc:
        # Job-level failure: the job itself is bad (unrenderable or malformed
        # payload). Leave the message on the queue so SQS redrives it; only mark
        # the job 'error' on the final attempt. Infrastructure errors (AWS
        # ClientError/timeouts, etc.) are deliberately NOT caught here. They
        # propagate and crash the worker so the orchestrator restarts it.
        logger.exception("Job %s failed during processing", job_id)
        trace.get_current_span().set_status(StatusCode.ERROR, str(exc))
        if receive_count >= SQS_MAX_RECEIVE_COUNT:
            update_job_status(
                job_id,
                "error",
                finished_timestamp_iso_8601=get_iso_8601_timestamp(),
                message="Internal rendering error",
            )
            record_job_failed()
            # Do not delete — let the visibility timeout expire so SQS
            # moves the message to the DLQ via the redrive policy.


@traced("worker.handle_dlq_message", kind=SpanKind.CONSUMER)
def handle_dlq_message(job_id: str, receipt_handle: str) -> None:
    """
    Handle a single DLQ message: update the job status to 'error' in DynamoDB
    if it's not already set to 'error', then delete the message from the DLQ.
    """
    trace.get_current_span().set_attribute("job.id", job_id)
    # Every call here is an infrastructure call (DynamoDB, SQS). There is no
    # job-level failure we can act on, so nothing is caught: an error propagates,
    # the message is left on the DLQ (not deleted), and the worker crashes so the
    # orchestrator restarts it. The traced span records the exception on the way out.
    job_item = get_print_job(job_id)
    current_status = job_item.get("status", None) if job_item else None

    if current_status != "error":
        update_job_status(
            job_id,
            "error",
            finished_timestamp_iso_8601=get_iso_8601_timestamp(),
            message="Job moved to DLQ after max retries",
        )
        logger.info("Updated job %s status to error from DLQ", job_id)
    else:
        logger.debug("Job %s already has error status, skipping update", job_id)

    delete_message(receipt_handle, get_dlq_url())
    logger.debug("Deleted DLQ message for job %s", job_id)


def run() -> None:
    """Main polling loop. Runs until a SIGTERM/SIGINT is received."""
    logger.info("Worker started, polling SQS queue...")
    touch_probe_file(STARTUP_PROBE_FILE)

    while not _shutdown:
        with ChromeBrowserManager() as browser:
            jobs_processed = 0
            while not _shutdown and (
                not BROWSER_RECYCLE_AFTER_JOBS or jobs_processed < BROWSER_RECYCLE_AFTER_JOBS
            ):
                touch_probe_file(LIVENESS_PROBE_FILE)
                # Wrap each poll cycle in a span so the SQS ReceiveMessage and the
                # resulting handle_message spans share one trace instead of the
                # receive floating as its own root span.
                with trace.get_tracer(__name__).start_as_current_span(
                    "worker.poll", kind=SpanKind.CONSUMER
                ):
                    # receive_messages only raises infrastructure errors (AWS
                    # ClientError/timeouts), which we cannot recover from here.
                    # They propagate and crash the worker so it is restarted.
                    messages = receive_messages(get_queue_url(), SQS_WAIT_TIME_SECONDS)

                    for message in messages:
                        touch_probe_file(LIVENESS_PROBE_FILE)
                        receipt_handle: str = message["ReceiptHandle"]
                        try:
                            job = parse_message_body(message)
                            job_id: str = job["job_id"]
                        except KeyError, ValueError:
                            logger.exception(
                                "Malformed SQS message, deleting: %s",
                                message.get("Body"),
                            )
                            delete_message(receipt_handle, get_queue_url())
                            continue

                        handle_message(job_id, job, message, browser)
                        jobs_processed += 1

                # Process DLQ messages. As with the main queue, receive_messages
                # only raises infrastructure errors, which propagate and crash
                # the worker rather than being swallowed and retried forever.
                dlq_messages = receive_messages(get_dlq_url(), SQS_DLQ_WAIT_TIME_SECONDS)
                for message in dlq_messages:
                    receipt_handle: str = message["ReceiptHandle"]
                    try:
                        job = parse_message_body(message)
                        job_id: str = job["job_id"]
                    except KeyError, ValueError:
                        logger.exception(
                            "Malformed DLQ message, deleting: %s",
                            message.get("Body"),
                        )
                        delete_message(receipt_handle, get_dlq_url())
                        continue

                    handle_dlq_message(job_id, receipt_handle)

            if not _shutdown:
                logger.info("Recycling Chrome after %d jobs", jobs_processed)
    logger.info("Worker stopped.")


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="service-print-renderer worker")
    _parser.add_argument(
        "-i",
        "--renderer-info",
        action="store_true",
        default=False,
        help="Print GPU/WebGL renderer info and exit",
    )
    _args = _parser.parse_args()

    if _args.renderer_info:
        init_logging()
        log_gpu_info()
        sys.exit(0)

    trace_provider, logger_provider, meter_provider = initialize_otel()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        run()
    except Exception:
        logger.exception("Unhandled exception in worker")
        sys.exit(1)
    finally:
        shutdown_otel(trace_provider, logger_provider, meter_provider)
