"""
service-print-renderer worker

Polls the SQS queue filled by service-print-api, renders print jobs,
and updates the corresponding DynamoDB items with the result.

Entry point: python -m app.worker
"""

import logging
import signal
import sys
import tempfile
from pathlib import Path

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from app.config.settings import SQS_ERROR_STATUS_MIN_RECEIVE_COUNT
from app.helpers.dynamo_db import update_job_status
from app.helpers.otel import initialize, setup_trace_provider, traced
from app.helpers.printing import render_to_pdf
from app.helpers.s3 import upload_pdf
from app.helpers.sqs_queue import (
    delete_message,
    make_message_visible,
    parse_message_body,
    receive_messages,
)
from app.helpers.utils import get_iso_8601_timestamp, init_logging

logger = logging.getLogger(__name__)

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown  # noqa: PLW0603
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown = True


@traced("worker.process_job")
def process_job(job: dict) -> str:
    """
    Render a single print job and upload the result to S3.

    Args:
        job: The deserialized job dict (as stored in DynamoDB / sent to SQS
             by service-print-api).

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

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    try:
        render_to_pdf(payload, pdf_path)
        return upload_pdf(job_id, pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)


@traced("worker.handle_message", kind=SpanKind.CONSUMER)
def handle_message(job_id: str, receipt_handle: str, job: dict, receive_count: int) -> None:
    """
    Handle a single SQS message end-to-end: render the job, update its final
    status in DynamoDB and delete the message from the queue on success.
    """
    trace.get_current_span().set_attribute("job.id", job_id)
    trace.get_current_span().set_attribute("messaging.receive_count", receive_count)
    try:
        pdf_url = process_job(job)
        update_job_status(
            job_id,
            "finished",
            finished_timestamp_iso_8601=get_iso_8601_timestamp(),
            pdf_url=pdf_url,
        )
        delete_message(receipt_handle)
        logger.info("Job %s completed successfully", job_id)
    except Exception as exc:
        logger.exception("Job %s failed during processing", job_id)
        trace.get_current_span().set_status(StatusCode.ERROR, str(exc))
        if receive_count >= SQS_ERROR_STATUS_MIN_RECEIVE_COUNT:
            update_job_status(
                job_id,
                "error",
                finished_timestamp_iso_8601=get_iso_8601_timestamp(),
                message="Internal rendering error",
            )
            delete_message(receipt_handle)
        else:
            # Make the message immediately visible again for retry
            make_message_visible(receipt_handle)


def run() -> None:
    """Main polling loop. Runs until a SIGTERM/SIGINT is received."""
    logger.info("Worker started, polling SQS queue...")

    while not _shutdown:
        try:
            messages = receive_messages()
        except Exception:
            logger.exception("Error receiving messages from SQS, retrying...")
            continue

        for message in messages:
            receipt_handle: str = message["ReceiptHandle"]
            receive_count: int = int(
                message.get("Attributes", {}).get("ApproximateReceiveCount", 1)
            )
            try:
                job = parse_message_body(message)
                job_id: str = job["job_id"]
            except KeyError, ValueError:
                logger.exception("Malformed SQS message, skipping: %s", message.get("Body"))
                # Delete the malformed message so it doesn't block the queue
                delete_message(receipt_handle)
                continue

            handle_message(job_id, receipt_handle, job, receive_count)

    logger.info("Worker stopped.")


if __name__ == "__main__":
    init_logging()
    initialize()
    setup_trace_provider()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        run()
    except Exception:
        logger.exception("Unhandled exception in worker")
        sys.exit(1)
