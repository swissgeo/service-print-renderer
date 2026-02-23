import os

"""
The Config contains everything needed to run the service. Most entries have a default
value and an environment value to override it.

"""
ENV_FILE = os.getenv("ENV_FILE", None)
if ENV_FILE:
    from dotenv import load_dotenv

    print(f"Running locally hence injecting env vars from {ENV_FILE}")  # noqa: T201
    load_dotenv(ENV_FILE, override=True, verbose=True)


LOCALSTACK_ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

DYNAMODB_TABLE_NAME: str = str(os.environ.get("DYNAMODB_TABLE_NAME", "service-print-jobs-local"))
SQS_QUEUE_NAME: str = str(os.environ.get("SQS_QUEUE_NAME", "service-print-jobs-queue-local"))

AWS_CONNECT_TIMEOUT: int = int(os.environ.get("AWS_CONNECT_TIMEOUT", "5"))
AWS_READ_TIMEOUT: int = int(os.environ.get("AWS_READ_TIMEOUT", "30"))

# SQS polling configuration
SQS_WAIT_TIME_SECONDS: int = int(os.environ.get("SQS_WAIT_TIME_SECONDS", "20"))
SQS_MAX_MESSAGES: int = int(os.environ.get("SQS_MAX_MESSAGES", "1"))
SQS_ERROR_STATUS_MIN_RECEIVE_COUNT: int = int(
    os.environ.get("SQS_ERROR_STATUS_MIN_RECEIVE_COUNT", "2")
)

# AWS_LOCAL
AWS_LOCAL: bool = os.environ.get("AWS_LOCAL", "false").lower() == "true"
if AWS_LOCAL:
    os.environ["AWS_ACCESS_KEY_ID"] = "123"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "123"  # dummy key  # noqa: S105
