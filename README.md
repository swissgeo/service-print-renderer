# service-print-renderer

| Branch | Status |
| ------ | --------- |
| develop | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=develop) [![codecov-develop](https://codecov.io/gh/swissgeo/service-print-renderer/branch/develop/graph/badge.svg)](https://codecov.io/gh/swissgeo/service-print-renderer) |
| main | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=main) [![codecov-main](https://codecov.io/gh/swissgeo/service-print-renderer/branch/main/graph/badge.svg)](https://codecov.io/gh/swissgeo/service-print-renderer) |

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Summary Of The Project](#summary-of-the-project)
- [Technologies](#technologies)
- [Setup and Run](#setup-and-run)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Start Moto](#start-moto)
  - [Run](#run)
  - [Test](#test)
- [Deployment configuration](#deployment-configuration)
  - [Kubernetes probes](#kubernetes-probes)
  - [Observability](#observability)
    - [Logging implementation](#logging-implementation)
    - [Local OTEL testing](#local-otel-testing)
- [Debugging](#debugging)
  - [WebGL renderer info](#webgl-renderer-info)

## Summary Of The Project

`service-print-renderer` is a background worker service responsible for consuming print jobs from an SQS queue and rendering them into PDF documents. The state of the print job is being updated in a dynamodb.

When `service-print-api` receives a print request from a client, it enqueues a job to SQS and returns a job ID. The renderer continuously polls that queue, picks up pending jobs one at a time, launches a headless Chrome browser via [Playwright](https://playwright.dev/python/), renders the web-portal page as a PDF, uploads it to S3 under the deterministic key `<S3_PDF_PREFIX>/<job_id>.pdf`, and updates the job status in DynamoDB to `finished`. The renderer does **not** store the PDF URL: because the S3 key is deterministic, `service-print-api` derives the PDF URL from the `job_id` once the status is `finished`. Clients can then query `service-print-api` with the job ID to check the status and retrieve the resulting document once it is ready.

Malformed SQS messages (unparseable body or missing `job_id`) are deleted directly from the main queue. Failed rendering jobs are not deleted — the worker lets the visibility timeout (`SQS_VISIBILITY_TIMEOUT`) expire so SQS redelivers the message and retries up to `SQS_MAX_RECEIVE_COUNT` times. Only on the final attempt is the job marked as `error` in DynamoDB; SQS then routes the message to the DLQ automatically via the redrive policy.

## Technologies

- [AWS SQS](https://aws.amazon.com/sqs/) - job queue
- [AWS DynamoDB](https://aws.amazon.com/dynamodb/) - job status tracking
- [AWS S3](https://aws.amazon.com/s3/) - PDF storage
- [Playwright (Python)](https://playwright.dev/python/docs/intro) - browser automation
- [Chrome headless](https://developer.chrome.com/docs/chromium/headless) - PDF rendering

## Setup and Run

### Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- `docker` and `docker compose`

### Setup

Copy the default env file and install dependencies:

```bash
make setup
```

`make setup` creates the virtual environment, installs all dependencies.

### Start Moto

Start the local AWS stack (DynamoDB, SQS, S3) and create the required resources:

> [!NOTE]
> Maybe you want to start the local stack from the project `service-print-api`. It starts exactly the same stack as in this project. Doing so, you have the possibility to test the entire print procedure.

```bash
make start-moto
```

This starts a [moto server](https://docs.getmoto.org/en/latest/docs/server_mode.html) container and runs the following init containers:

| Container | Action |
| --------- | ------ |
| `init-dynamo` | Creates the DynamoDB table (`DYNAMODB_TABLE_NAME`) |
| `init-sqs` | Creates the DLQ (`SQS_DL_QUEUE_NAME`) and the main SQS queue (`SQS_QUEUE_NAME`) with a redrive policy pointing to the DLQ |
| `init-s3` | Creates the S3 bucket (`S3_BUCKET_NAME`) with a public-read policy |

If a moto server is already running (e.g. started from `service-print-api`), `make start-moto` reuses it and only reruns the init containers.

To verify the S3 bucket was created:

```bash
AWS_ACCESS_KEY_ID=123 AWS_SECRET_ACCESS_KEY=123 aws s3 ls --endpoint-url http://localhost:5000
```

### Run

```bash
make run
```

The worker polls the SQS queue continuously, processes incoming jobs, updates the dynamodb with the state of the process and uploads the resulting PDFs to S3.

### Test

```bash
make test              # run tests with HTML coverage report
make test-ci           # run tests with XML coverage report (used in CI)
make lint              # run ruff linter + ty type checker
make ci-check-format   # run ruff format and checks if any files changed (used in CI)
```

## Deployment configuration

The service is configured entirely via environment variables:

| Env | Default | Description |
| --- | ------- | ----------- |
| `AWS_LOCAL` | `false` | Set to `true` to point AWS clients at the moto server instead of real AWS |
| `MOTO_HOST` | `localhost` | Hostname of the moto server (local development only) |
| `MOTO_PORT` | `5000` | Port of the moto server (local development only) |
| `AWS_REGION` | `eu-central-1` | AWS region |
| `AWS_CONNECT_TIMEOUT` | `5` | Timeout in seconds for establishing a connection to AWS services |
| `AWS_READ_TIMEOUT` | `30` | Timeout in seconds for reading a response from AWS services |
| `DYNAMODB_TABLE_NAME` | `service-print-jobs-local` | DynamoDB table storing print job status |
| `SQS_QUEUE_NAME` | `service-print-jobs-queue-local` | SQS queue name |
| `SQS_DL_QUEUE_NAME` | `service-print-jobs-dlq-local` | SQS dead-letter queue name |
| `SQS_MAX_RECEIVE_COUNT` | `3` | Number of times a message can be received before SQS routes it to the DLQ automatically |
| `SQS_VISIBILITY_TIMEOUT` | `90` | How long (in seconds) a received message is hidden from other consumers; after expiry SQS redelivers it (or routes to DLQ if `maxReceiveCount` is reached). Must exceed the worst-case render time so a slow job is not redelivered while still processing |
| `SQS_WAIT_TIME_SECONDS` | `20` | Long-polling wait time in seconds when reading from SQS |
| `SQS_DLQ_WAIT_TIME_SECONDS` | `2` | Polling wait time in seconds when reading from SQS DLQ |
| `SQS_MAX_MESSAGES` | `1` | Maximum number of messages to retrieve per SQS poll |
| `S3_BUCKET_NAME` | `service-print-jobs-local` | S3 bucket where rendered PDFs are stored |
| `S3_PDF_CACHE_CONTROL_MAX_AGE` | `3600` | TTL in seconds for the `Cache-Control: max-age` header set on PDFs uploaded to S3; controls how long CloudFront and browsers cache the PDF |
| `PORTAL_URL` | - | web-portal endpoint (**required**). The per-job URL is built as `<PORTAL_URL without trailing /?>/<print_lang>/print?<query>`, e.g. `https://www.dev.sgdi.tech/en/print?state=…&z=4&print_format=a3&…` |
| `TIMEOUT_LOADING_WEB_PAGE` | `30000` | Browser page-load timeout in milliseconds |
| `USE_GPU` | `false` | Set to `true` to use the local machine's GPU (native OpenGL) instead of the SwiftShader software rasterizer. For local development only |
| `BROWSER_RECYCLE_AFTER_JOBS` | `10` | Restart Chrome after this many jobs to prevent memory accumulation; set to `0` to disable |
| `BROWSER_NAVIGATION_RETRIES` | `3` | Number of times to retry page navigation on `ERR_NETWORK_CHANGED` before failing the job |

### Kubernetes probes

The worker writes probe files to signal its state to Kubernetes:

| Probe | File (default) | Env var | Behaviour |
| ----- | -------------- | ------- | --------- |
| Startup | `/tmp/startup_probe` | `STARTUP_PROBE_FILE` | Created once when the worker starts; never removed |
| Liveness | `/tmp/liveness_probe` | `LIVENESS_PROBE_FILE` | Touched after every polling and every printing cycle |

Configure the Kubernetes probes as `exec` checks:

```yaml
startupProbe:
  exec:
    command: ["test", "-f", "/tmp/startup_probe"]
livenessProbe:
  exec:
    command: ["sh", "-c", "test $(( $(date +%s) - $(date +%s -r /tmp/liveness_probe) )) -lt 60"]
```

The liveness check passes only if the file was touched within the last 60 seconds, catching a stalled worker even if the file still exists from a previous cycle.

You can verify the probe files manually while the worker is running:

```bash
# startup probe: exists once the worker loop has started
test -f /tmp/startup_probe && echo "started" || echo "not started"

# liveness probe: touched every polling cycle, must be < 60s old
test $(( $(date +%s) - $(date +%s -r /tmp/liveness_probe) )) -lt 60 && echo "alive" || echo "not alive"
```

### Observability

The worker exports **traces** via OpenTelemetry (OTLP) by default, and can also export
**logs** via OTLP when the OTEL logging config is used (see
[Logging implementation](#logging-implementation)); metrics are not implemented yet. With
`OTEL_ENABLE_BOTOCORE=true`, every DynamoDB, SQS, and S3 call is also captured as a span.

| Env | Default | Description |
| --- | ------- | ----------- |
| `OTEL_SDK_DISABLED` | `false` | Set to `true` to disable all OTEL instrumentation |
| `OTEL_ENABLE_BOTOCORE` | `false` | Set to `true` to trace DynamoDB, SQS, and S3 calls |
| `OTEL_ENABLE_OTLP_EXPORTER` | `true` | Export spans/logs to the OTLP collector; set `false` to print spans to the console instead (no collector required) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC endpoint of the collector |
| `OTEL_EXPORTER_OTLP_INSECURE` | `false` | Set to `true` for an insecure (non-TLS) connection. Required for a plaintext local collector |
| `OTEL_EXPORTER_OTLP_HEADERS` | - | Optional headers for the OTLP collector (e.g. for authentication) |
| `OTEL_RESOURCE_ATTRIBUTES` | - | Resource attributes attached to all telemetry (e.g. `service.name=service-print-renderer`) |

#### Logging implementation

When the OTEL logging config (`app/config/logging-cfg-otel.yaml`) is used, logs are exported
through the OpenTelemetry `LoggerProvider` (the `otel` handler).

#### Local OTEL testing

1. Start the local OTEL collector and Jaeger:

   ```bash
   make start-otel
   ```

2. Run the worker. Traces export by default; to also export logs via OTLP, point
   `LOGGING_CFG` at the OTEL logging config:

   ```bash
   LOGGING_CFG=app/config/logging-cfg-otel.yaml make run
   ```

View the full traces in the Jaeger UI at **<http://localhost:16686>**. Stop the stack with
`make stop-otel`.

## Debugging

### WebGL renderer info

To verify that headless Chrome can access WebGL and report the expected renderer, run the worker with the `-i` / `--renderer-info` flag:

```bash
make renderer-info
# or directly: uv run python -m app.worker --renderer-info
```

This launches a headless Chrome instance, evaluates a WebGL probe, logs the hardware-acceleration status and the renderer name, then exits. No queue polling or AWS calls are made.
