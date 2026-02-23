import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBServiceResource
    from mypy_boto3_dynamodb.service_resource import Table

from app.config.settings import (
    AWS_CONNECT_TIMEOUT,
    AWS_LOCAL,
    AWS_READ_TIMEOUT,
    AWS_REGION,
    DYNAMODB_TABLE_NAME,
    LOCALSTACK_ENDPOINT,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_dynamodb() -> DynamoDBServiceResource:
    boto_config = Config(
        connect_timeout=AWS_CONNECT_TIMEOUT,
        read_timeout=AWS_READ_TIMEOUT,
    )
    try:
        if AWS_LOCAL:
            logger.info("Connecting to locally running dynamodb")
            dynamodb = cast(
                "DynamoDBServiceResource",
                boto3.resource(
                    "dynamodb",
                    endpoint_url=LOCALSTACK_ENDPOINT,
                    region_name=AWS_REGION,
                    config=boto_config,
                ),
            )
        else:
            dynamodb = cast(
                "DynamoDBServiceResource", boto3.resource("dynamodb", config=boto_config)
            )
    except ClientError:
        logger.exception("Error connecting dynamodb")
        raise
    else:
        return dynamodb


def get_dynamodb_table() -> Table:
    dynamodb: DynamoDBServiceResource = get_dynamodb()
    return dynamodb.Table(DYNAMODB_TABLE_NAME)  # ty: ignore[unresolved-attribute]


def get_print_job(job_id: str) -> dict[str, Any] | None:
    """
    Retrieves a print job item from DynamoDB by job_id.

    Returns the item dict if found, or None if no matching job exists.
    """
    dynamodb_table = get_dynamodb_table()
    try:
        result = dynamodb_table.get_item(Key={"job_id": job_id})
    except ConnectTimeoutError:
        logger.exception("Connection timeout looking up print job %s", job_id)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout looking up print job %s", job_id)
        raise
    except ClientError:
        logger.exception("Error looking up print job %s", job_id)
        raise
    if "Item" in result:
        return dict(result["Item"])
    return None


def update_job_status(job_id: str, status: str, **extra_fields: Any) -> None:
    """
    Updates the status and any extra fields of a print job in DynamoDB.

    Args:
        job_id: The job identifier (partition key).
        status: The new status value (e.g. "started", "completed", "error").
        **extra_fields: Additional attributes to set on the item
                        (e.g. started_timestamp_iso_8601, finished_timestamp_iso_8601,
                        pdf_url, message).
    """
    dynamodb_table = get_dynamodb_table()

    # Build UpdateExpression dynamically from status + extra_fields
    fields = {"status": status, **extra_fields}
    set_expressions = [f"#attr_{k} = :val_{k}" for k in fields]
    update_expression = "SET " + ", ".join(set_expressions)
    expression_attribute_names = {f"#attr_{k}": k for k in fields}
    expression_attribute_values = {f":val_{k}": v for k, v in fields.items()}

    try:
        dynamodb_table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
        )
        logger.debug("Updated job %s in DynamoDB (status=%s)", job_id, status)
    except ConnectTimeoutError:
        logger.exception("Connection timeout updating job %s in DynamoDB", job_id)
        raise
    except ReadTimeoutError:
        logger.exception("Read timeout updating job %s in DynamoDB", job_id)
        raise
    except ClientError:
        logger.exception("Error updating job %s in DynamoDB", job_id)
        raise
