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

# Webmapviewer endpoints
VIEWER_URL_MAP_RASTER: str = os.environ.get("VIEWER_URL_MAP_RASTER", "")
VIEWER_URL_MAP: str = os.environ.get("VIEWER_URL_MAP", "")
VIEWER_URL_LEGEND: str = os.environ.get("VIEWER_URL_LEGEND", "")

# Rendering behaviour
TIMEOUT_LOADING_WEB_PAGE: int = int(os.environ.get("TIMEOUT_LOADING_WEB_PAGE", "30000"))
ROUND_UP_TO_NEXT_Z_INT: bool = os.environ.get("ROUND_UP_TO_NEXT_Z_INT", "true").lower() == "true"
GO_ONE_Z_FURTHER: bool = os.environ.get("GO_ONE_Z_FURTHER", "false").lower() == "true"
# Recycle (restart) Chrome after this many jobs to prevent memory accumulation.
# 0 disables recycling.
BROWSER_RECYCLE_AFTER_JOBS: int = int(os.environ.get("BROWSER_RECYCLE_AFTER_JOBS", "10"))
# Number of times to retry page navigation on ERR_NETWORK_CHANGED before failing.
BROWSER_NAVIGATION_RETRIES: int = int(os.environ.get("BROWSER_NAVIGATION_RETRIES", "3"))

# Chrome launch flags for headless rendering.
# USE_GPU=true switches to ANGLE over Vulkan (uses system GPU via nvidia_icd / mesa).
# Default (false) uses ANGLE over SwiftShader for CI/containers (no GPU required).
# See https://github.com/GoogleChrome/chrome-launcher/blob/main/docs/chrome-flags-for-tools.md for
# more details on flags.
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
    # Disable various background network services, including extension updating, safe browsing
    # service, upgrade detector, translate, UMA.
    "--disable-background-networking",
    # Don't update the browser 'components' listed at chrome://components/
    "--disable-component-update",
    # Disables Domain Reliability Monitoring, which tracks whether the browser has difficulty
    # contacting Google-owned sites and uploads reports to Google
    "--disable-domain-reliability",
    # Disable syncing to a Google account
    "--disable-sync",
    # Disable reporting to UMA, but allows for collection
    "--metrics-recording-only",
    "--disable-features=AutofillServerCommunication",
    "--disable-features=MediaRouter",
    # Disable quick mode to avoid UDP background activity,
    # When quick mode is enable, chrome open UDP sockets to its own QUIC server
    # So we disable it to avoid background noise activity
    # See https://en.wikipedia.org/wiki/QUIC
    "--disable-quic",
]

# Paper sizes at 96 dpi (width, height) in pixels — portrait orientation
PAPER_SIZES: dict[str, tuple[int, int]] = {
    "a0": (3179, 4494),
    "a1": (2245, 3179),
    "a2": (1587, 2245),
    "a3": (1123, 1587),
    "a4": (794, 1123),
    "a5": (559, 794),
    "a6": (397, 559),
}

# WMTS scale denominator → zoom level matrix for LV95
# https://api3.geo.admin.ch/services/sdiservices.html#wmts
MATRIX_LV95: dict[int, int] = {
    0: 2456694,
    1: 1889765,
    2: 944882,
    3: 377953,
    4: 188976,
    5: 75591,
    6: 37795,
    7: 18898,
    8: 9449,
    9: 7559,
    10: 3780,
    11: 1890,
    12: 945,
    13: 378,
}
