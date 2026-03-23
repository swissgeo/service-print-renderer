"""S3 helper for uploading rendered PDFs."""

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

if TYPE_CHECKING:
    from pathlib import Path

    from mypy_boto3_s3 import S3Client

from app.config.settings import (
    AWS_CONNECT_TIMEOUT,
    AWS_LOCAL,
    AWS_READ_TIMEOUT,
    AWS_REGION,
    LOCALSTACK_ENDPOINT,
    PRINT_API_BASE_URL,
    S3_BUCKET_NAME,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_s3_client() -> S3Client:
    boto_config = Config(
        connect_timeout=AWS_CONNECT_TIMEOUT,
        read_timeout=AWS_READ_TIMEOUT,
    )
    try:
        if AWS_LOCAL:
            logger.info("Connecting to locally running S3")
            local_config = Config(
                connect_timeout=AWS_CONNECT_TIMEOUT,
                read_timeout=AWS_READ_TIMEOUT,
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )
            return boto3.client(
                "s3",
                endpoint_url=LOCALSTACK_ENDPOINT,
                region_name=AWS_REGION,
                config=local_config,
            )
        return boto3.client("s3", config=boto_config)
    except ClientError:
        logger.exception("Error connecting to S3")
        raise


def upload_pdf(job_id: str, pdf_path: Path) -> str:
    """Upload a PDF to S3 and return its URL.

    Args:
        job_id: The print job identifier, used as the S3 object key.
        pdf_path: Local path to the PDF file to upload.

    Returns:
        The URL at which the PDF can be retrieved.

    Raises:
        ClientError: If the upload fails.
    """
    s3 = get_s3_client()
    key = f"{job_id}.pdf"
    try:
        s3.upload_file(
            str(pdf_path),
            S3_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        logger.info("Uploaded PDF for job %s to s3://%s/%s", job_id, S3_BUCKET_NAME, key)
    except ConnectTimeoutError:
        logger.exception("Connection timeout uploading PDF for job %s", job_id)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout uploading PDF for job %s", job_id)
        raise
    except ClientError:
        logger.exception("Error uploading PDF for job %s to S3", job_id)
        raise

    pdf_url = f"{PRINT_API_BASE_URL}/api/print/pdf/{key}"
    logger.debug("PDF URL for job %s: %s", job_id, pdf_url)
    return pdf_url
