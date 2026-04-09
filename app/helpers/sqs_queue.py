import json
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

from app.config.settings import (
    AWS_CONNECT_TIMEOUT,
    AWS_LOCAL,
    AWS_READ_TIMEOUT,
    AWS_REGION,
    MOTO_ENDPOINT,
    SQS_DL_QUEUE_NAME,
    SQS_MAX_MESSAGES,
    SQS_QUEUE_NAME,
)

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sqs_client() -> SQSClient:
    """
    Initializes and returns an SQS client object.

    Connects to LocalStack if AWS_LOCAL=true, otherwise to AWS.
    """
    boto_config = Config(
        connect_timeout=AWS_CONNECT_TIMEOUT,
        read_timeout=AWS_READ_TIMEOUT,
    )
    try:
        if AWS_LOCAL:
            logger.info("Connecting to locally running SQS")
            sqs = boto3.client(
                "sqs",
                endpoint_url=MOTO_ENDPOINT,
                region_name=AWS_REGION,
                config=boto_config,
            )
        else:
            sqs = boto3.client("sqs", config=boto_config)
    except ClientError:
        logger.exception("Error connecting to SQS")
        raise
    else:
        return sqs


@lru_cache(maxsize=1)
def get_queue_url() -> str:
    """Returns the URL of the configured SQS queue."""
    sqs = get_sqs_client()
    return sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)["QueueUrl"]


def receive_messages(queue_url: str, wait_time_seconds: int) -> list[dict[str, Any]]:
    """
    Polls an SQS queue for messages using long polling.

    Args:
        queue_url: The URL of the queue to poll.

    Returns a list of raw SQS message dicts. Each message contains at least
    'Body' (JSON string of the job item), 'ReceiptHandle' (needed for deletion),
    and 'Attributes' including 'ApproximateReceiveCount'.
    """
    sqs = get_sqs_client()
    try:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=SQS_MAX_MESSAGES,
            WaitTimeSeconds=wait_time_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        logger.debug("Received %d message(s) from SQS queue %s", len(messages), queue_url)
    except ConnectTimeoutError:
        logger.exception("Connection timeout receiving messages from SQS queue %s", queue_url)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout receiving messages from SQS queue %s", queue_url)
        raise
    except ClientError:
        logger.exception("Error receiving messages from SQS queue %s", queue_url)
        raise
    return messages  # type: ignore[return-value]


def delete_message(receipt_handle: str, queue_url: str) -> None:
    """
    Deletes a successfully processed message from the SQS queue.

    Args:
        receipt_handle: The receipt handle returned by receive_message.
        queue_url: The URL of the queue from which to delete the message.
    """
    sqs = get_sqs_client()
    try:
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        logger.debug("Deleted message from SQS queue %s", queue_url)
    except ConnectTimeoutError:
        logger.exception("Connection timeout deleting message from SQS queue %s", queue_url)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout deleting message from SQS queue %s", queue_url)
        raise
    except ClientError:
        logger.exception("Error deleting message from SQS queue %s", queue_url)
        raise


@lru_cache(maxsize=1)
def get_dlq_url() -> str:
    """Returns the URL of the configured SQS dead-letter queue."""
    sqs = get_sqs_client()
    return sqs.get_queue_url(QueueName=SQS_DL_QUEUE_NAME)["QueueUrl"]


def parse_message_body(message: dict[str, Any]) -> dict[str, Any]:
    """Deserializes the JSON body of an SQS message into a dict."""
    return dict(json.loads(message["Body"]))
