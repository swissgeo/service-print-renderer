import os
import tempfile
from pathlib import Path

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

# Writable scratch directory. With a read-only root filesystem, point it at a
# mounted writable volume.
# Resolved without tempfile.gettempdir(), which probes the filesystem and raises at
# import time when nothing is writable.
TMP_DIR: str = os.environ.get("TMP_DIR") or "/tmp"  # noqa: S108
_TMP_PATH = Path(TMP_DIR)

# Playwright and Chrome are child processes, so the environment is the only way to
# redirect their scratch data (temp profile, artifacts, caches) away from /tmp and
# $HOME.
os.environ["TMPDIR"] = TMP_DIR
os.environ["TMP"] = TMP_DIR
os.environ["TEMP"] = TMP_DIR
os.environ.setdefault("XDG_CONFIG_HOME", str(_TMP_PATH / "xdg-config"))
os.environ.setdefault("XDG_CACHE_HOME", str(_TMP_PATH / "xdg-cache"))
tempfile.tempdir = TMP_DIR

CHROME_USER_DATA_DIR: str = str(_TMP_PATH / "user_data")

# Kubernetes probe files
STARTUP_PROBE_FILE: str = os.environ.get("STARTUP_PROBE_FILE", str(_TMP_PATH / "startup_probe"))
LIVENESS_PROBE_FILE: str = os.environ.get("LIVENESS_PROBE_FILE", str(_TMP_PATH / "liveness_probe"))

# SQS polling configuration
SQS_WAIT_TIME_SECONDS: int = int(os.environ.get("SQS_WAIT_TIME_SECONDS", "20"))
SQS_DLQ_WAIT_TIME_SECONDS: int = int(os.environ.get("SQS_DLQ_WAIT_TIME_SECONDS", "2"))
SQS_MAX_MESSAGES: int = int(os.environ.get("SQS_MAX_MESSAGES", "1"))
SQS_MAX_RECEIVE_COUNT: int = int(os.environ.get("SQS_MAX_RECEIVE_COUNT", "3"))
# Must exceed the worst-case render time (2 x TIMEOUT_LOADING_WEB_PAGE + PDF render/upload)
# so a slow job is never redelivered to another consumer while still being processed.
SQS_VISIBILITY_TIMEOUT: int = int(os.environ.get("SQS_VISIBILITY_TIMEOUT", "90"))

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
    #
    # --- Prevent Chrome from calling home  ---
    # See chrome-flags-for-tools.md#background-networking.
    #
    # (1) Stop the recurring background features from even trying.
    "--disable-background-networking",  # extension/safebrowsing/upgrade/translate/UMA fetches
    "--disable-component-update",  # no chrome://components downloads
    "--disable-domain-reliability",  # no reliability beacons to Google
    "--disable-sync",  # no Google-account sync
    "--disable-breakpad",  # no crash-dump generation...
    "--disable-crash-reporter",  # ...and no upload of crashes to Google
    "--disable-client-side-phishing-detection",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-pings",  # no hyperlink-auditing pings
    "--metrics-recording-only",  # record UMA but never upload
    # Force everything onto TCP: no QUIC/HTTP-3 UDP/443 sockets, so the only UDP
    # left is DNS to the cluster resolver and all egress is covered by the
    # hostname sinkhole below (which applies pre-transport, TCP and QUIC alike).
    "--disable-quic",
    # Exactly ONE --disable-features flag (Chrome honors only the last occurrence).
    # DnsOverHttps is disabled so DoH can't open its own egress to a resolver.
    (
        "--disable-features="
        "AutofillServerCommunication,"
        "MediaRouter,"
        "DialMediaRouteProvider,"
        "OptimizationHints,"
        "Translate,"
        "InterestFeedContentSuggestions,"
        "DnsOverHttps"
    ),
    # (2) Sinkhole the residual startup phone-home lookups to loopback so the
    # packet never leaves the pod and the CNI logs nothing. A real portal render
    # was verified to use NO Google-owned hosts (no fonts/gstatic), so wildcarding
    # the Google families is safe. If the portal ever adds a Google-hosted asset
    # (e.g. fonts.googleapis.com), append ",EXCLUDE <that-host>" to un-sinkhole it.
    # Observed phone-home hosts: accounts / android.clients / clients2 / mtalk /
    # www .google.com and safebrowsingohttpgateway.googleapis.com.
    "--host-resolver-rules=MAP *.google.com 127.0.0.1,MAP *.googleapis.com 127.0.0.1",
]
