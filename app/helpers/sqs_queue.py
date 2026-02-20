import json
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

from app.config.settings import (
    AWS_CONNECT_TIMEOUT,
    AWS_DEFAULT_REGION,
    AWS_LOCAL,
    AWS_READ_TIMEOUT,
    LOCALSTACK_PORT,
    SQS_MAX_MESSAGES,
    SQS_QUEUE_NAME,
    SQS_WAIT_TIME_SECONDS,
)

# Attributes requested from SQS on every receive_message call
_SQS_ATTRIBUTES = ["ApproximateReceiveCount"]

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
                endpoint_url=f"http://localhost:{LOCALSTACK_PORT}",
                region_name=AWS_DEFAULT_REGION,
                config=boto_config,
            )
        else:
            sqs = boto3.client("sqs", config=boto_config)
    except ClientError:
        logger.exception("Error connecting to SQS")
        raise
    else:
        return sqs


def get_queue_url() -> str:
    """Returns the URL of the configured SQS queue."""
    sqs = get_sqs_client()
    return sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)["QueueUrl"]


def receive_messages() -> list[dict[str, Any]]:
    """
    Polls the SQS queue for messages using long polling.

    Returns a list of raw SQS message dicts. Each message contains at least
    'Body' (JSON string of the job item), 'ReceiptHandle' (needed for deletion),
    and 'Attributes' including 'ApproximateReceiveCount'.
    """
    sqs = get_sqs_client()
    try:
        queue_url = get_queue_url()
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=SQS_MAX_MESSAGES,
            WaitTimeSeconds=SQS_WAIT_TIME_SECONDS,
            AttributeNames=_SQS_ATTRIBUTES,
        )
        messages = response.get("Messages", [])
        logger.debug("Received %d message(s) from SQS queue %s", len(messages), SQS_QUEUE_NAME)
    except ConnectTimeoutError:
        logger.exception("Connection timeout receiving messages from SQS queue %s", SQS_QUEUE_NAME)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout receiving messages from SQS queue %s", SQS_QUEUE_NAME)
        raise
    except ClientError:
        logger.exception("Error receiving messages from SQS queue %s", SQS_QUEUE_NAME)
        raise
    return messages  # type: ignore[return-value]


def delete_message(receipt_handle: str) -> None:
    """
    Deletes a successfully processed message from the SQS queue.

    Args:
        receipt_handle: The receipt handle returned by receive_message.
    """
    sqs = get_sqs_client()
    try:
        queue_url = get_queue_url()
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
        logger.debug("Deleted message from SQS queue %s", SQS_QUEUE_NAME)
    except ConnectTimeoutError:
        logger.exception("Connection timeout deleting message from SQS queue %s", SQS_QUEUE_NAME)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout deleting message from SQS queue %s", SQS_QUEUE_NAME)
        raise
    except ClientError:
        logger.exception("Error deleting message from SQS queue %s", SQS_QUEUE_NAME)
        raise


def make_message_visible(receipt_handle: str) -> None:
    """
    Makes an SQS message immediately visible again for reprocessing.

    Args:
        receipt_handle: The receipt handle returned by receive_message.
    """
    sqs = get_sqs_client()
    try:
        queue_url = get_queue_url()
        sqs.change_message_visibility(
            QueueUrl=queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=0
        )
        logger.debug("Made message visible again in SQS queue %s", SQS_QUEUE_NAME)
    except ConnectTimeoutError:
        logger.exception(
            "Connection timeout making message visible in SQS queue %s", SQS_QUEUE_NAME
        )
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout making message visible in SQS queue %s", SQS_QUEUE_NAME)
        raise
    except ClientError:
        logger.exception("Error making message visible in SQS queue %s", SQS_QUEUE_NAME)
        raise


def parse_message_body(message: dict[str, Any]) -> dict[str, Any]:
    """Deserializes the JSON body of an SQS message into a dict."""
    return dict(json.loads(message["Body"]))
