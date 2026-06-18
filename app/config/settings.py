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


MOTO_HOST = os.environ.get("MOTO_HOST", "localhost")
MOTO_PORT = os.environ.get("MOTO_PORT", "5000")
MOTO_ENDPOINT = f"http://{MOTO_HOST}:{MOTO_PORT}"
AWS_REGION = os.environ.get("AWS_REGION", "eu-central-1")

DYNAMODB_TABLE_NAME: str = str(os.environ.get("DYNAMODB_TABLE_NAME", "service-print-jobs-local"))
SQS_QUEUE_NAME: str = str(os.environ.get("SQS_QUEUE_NAME", "service-print-jobs-queue-local"))
SQS_DL_QUEUE_NAME: str = str(os.environ.get("SQS_DL_QUEUE_NAME", "service-print-jobs-dlq-local"))

AWS_CONNECT_TIMEOUT: int = int(os.environ.get("AWS_CONNECT_TIMEOUT", "5"))
AWS_READ_TIMEOUT: int = int(os.environ.get("AWS_READ_TIMEOUT", "30"))

# Kubernetes probe files
STARTUP_PROBE_FILE: str = os.environ.get("STARTUP_PROBE_FILE", "/tmp/startup_probe")  # noqa: S108
LIVENESS_PROBE_FILE: str = os.environ.get("LIVENESS_PROBE_FILE", "/tmp/liveness_probe")  # noqa: S108

# SQS polling configuration
SQS_WAIT_TIME_SECONDS: int = int(os.environ.get("SQS_WAIT_TIME_SECONDS", "20"))
SQS_DLQ_WAIT_TIME_SECONDS: int = int(os.environ.get("SQS_DLQ_WAIT_TIME_SECONDS", "2"))
SQS_MAX_MESSAGES: int = int(os.environ.get("SQS_MAX_MESSAGES", "1"))
SQS_MAX_RECEIVE_COUNT: int = int(os.environ.get("SQS_MAX_RECEIVE_COUNT", "3"))
SQS_VISIBILITY_TIMEOUT: int = int(os.environ.get("SQS_VISIBILITY_TIMEOUT", "60"))

# AWS_LOCAL
AWS_LOCAL: bool = os.environ.get("AWS_LOCAL", "false").lower() == "true"
if AWS_LOCAL:
    os.environ["AWS_ACCESS_KEY_ID"] = "123"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "123"  # dummy key  # noqa: S105

# S3
S3_BUCKET_NAME: str = os.environ.get("S3_BUCKET_NAME", "service-print-pdf-local")
S3_PDF_PREFIX: str = os.environ.get("S3_PDF_PREFIX", "api/wps/v1/print/pdf")
S3_PDF_CACHE_CONTROL_MAX_AGE: int = int(os.environ.get("S3_PDF_CACHE_CONTROL_MAX_AGE", "3600"))

# web-portal endpoint. The renderer builds the per-job URL as
# "<PORTAL_URL without trailing /?>/<print_lang>/print?<query>".
PORTAL_URL: str = os.environ.get("PORTAL_URL", "")

# Rendering behaviour
TIMEOUT_LOADING_WEB_PAGE: int = int(os.environ.get("TIMEOUT_LOADING_WEB_PAGE", "30000"))
# Recycle (restart) Chrome after this many jobs to prevent memory accumulation.
# 0 disables recycling.
BROWSER_RECYCLE_AFTER_JOBS: int = int(os.environ.get("BROWSER_RECYCLE_AFTER_JOBS", "10"))
# Number of times to retry page navigation on ERR_NETWORK_CHANGED before failing.
BROWSER_NAVIGATION_RETRIES: int = int(os.environ.get("BROWSER_NAVIGATION_RETRIES", "3"))

# Chrome launch flags for headless rendering.
# USE_GPU=true switches to ANGLE over Vulkan (uses system GPU via nvidia_icd / mesa).
# Default (false) uses ANGLE over SwiftShader for CI/containers (no GPU required).
_USE_GPU: bool = os.environ.get("USE_GPU", "false").lower() == "true"
BROWSER_LAUNCH_ARGS: list[str] = [
    *(
        ["--use-gl=angle", "--use-angle=vulkan"]
        if _USE_GPU
        else ["--use-gl=angle", "--use-angle=swiftshader"]
    ),
    # --ozone-platform=wayland is only needed when a Wayland display is available
    *(["--ozone-platform=wayland"] if os.environ.get("WAYLAND_DISPLAY") else []),
    "--enable-webgl",
    "--no-sandbox",  # covers GPU sandbox too; --disable-gpu-sandbox is redundant
    "--disable-dev-shm-usage",  # prevents Chrome from crashing on limited /dev/shm in Docker
]
