# service-print-renderer

| Branch | Status |
| ------ | --------- |
| develop | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=develop) |
| main | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=main) |

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Summary Of The Project](#summary-of-the-project)
- [Technologies](#technologies)
- [Setup and Run](#setup-and-run)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Start LocalStack](#start-localstack)
  - [Run](#run)
  - [Test](#test)
- [Deployment configuration](#deployment-configuration)
  - [Kubernetes probes](#kubernetes-probes)
  - [OpenTelemetry (tracing)](#opentelemetry-tracing)
    - [Local tracing setup](#local-tracing-setup)
- [Debugging](#debugging)
  - [WebGL renderer info](#webgl-renderer-info)

## Summary Of The Project

`service-print-renderer` is a background worker service responsible for consuming print jobs from an SQS queue and rendering them into PDF documents.

When `service-print-api` receives a print request from a client, it enqueues a job to SQS and returns a job ID. The renderer continuously polls that queue, picks up pending jobs one at a time, launches a headless Chrome browser via [Playwright](https://playwright.dev/python/), renders the webmapviewer page as a PDF, uploads it to S3, and updates the job status in DynamoDB. The `pdf_url` stored in DynamoDB is an S3 presigned URL valid for `S3_PRESIGNED_URL_EXPIRY` seconds. Clients can then query `service-print-api` with the job ID to check the status and retrieve the resulting document once it is ready.

Malformed SQS messages (unparseable body or missing `job_id`) are not deleted by the worker. Instead they are left in the queue so that SQS can apply the configured **redrive policy**: once a message has been received `maxReceiveCount` times without being deleted, SQS moves it automatically to the dead-letter queue (DLQ).

## Technologies

- [AWS SQS](https://aws.amazon.com/sqs/) — job queue
- [AWS DynamoDB](https://aws.amazon.com/dynamodb/) — job status tracking
- [AWS S3](https://aws.amazon.com/s3/) — PDF storage
- [Playwright (Python)](https://playwright.dev/python/docs/intro) — browser automation
- [Chrome headless](https://developer.chrome.com/docs/chromium/headless) — PDF rendering

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

### Start LocalStack

Start the local AWS stack (DynamoDB, SQS, S3) and create the required resources:

> [!NOTE]
> Maybe you want to start the local stack from the project `service-print-api` it is starting exactly the same local stack as in this project. Doing so, you have the possibility to test the entire print procedure. 


```bash
make start-localstack
```

This runs `docker compose up -d` which starts LocalStack and the following init containers:

| Container | Action |
| --------- | ------ |
| `init-dynamo` | Creates the DynamoDB table (`DYNAMODB_TABLE_NAME`) |
| `init-sqs` | Creates the SQS queue (`SQS_QUEUE_NAME`) |
| `init-s3` | Creates the S3 bucket (`S3_BUCKET_NAME`) |

To verify the S3 bucket was created:

```bash
aws s3 ls --endpoint-url http://localhost:4566
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
| `AWS_LOCAL` | `false` | Set to `true` to point AWS clients at LocalStack instead of real AWS |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint URL of the LocalStack instance (local development only) |
| `AWS_REGION` | `eu-central-1` | AWS region |
| `AWS_CONNECT_TIMEOUT` | `5` | Timeout in seconds for establishing a connection to AWS services |
| `AWS_READ_TIMEOUT` | `30` | Timeout in seconds for reading a response from AWS services |
| `DYNAMODB_TABLE_NAME` | `service-print-jobs-local` | DynamoDB table storing print job status |
| `SQS_QUEUE_NAME` | `service-print-jobs-queue-local` | SQS queue name |
| `SQS_WAIT_TIME_SECONDS` | `20` | Long-polling wait time in seconds when reading from SQS |
| `SQS_MAX_MESSAGES` | `1` | Maximum number of messages to retrieve per SQS poll |
| `SQS_ERROR_STATUS_MIN_RECEIVE_COUNT` | `2` | Minimum receive count before a job is marked as error and removed from the queue |
| `S3_BUCKET_NAME` | `service-print-jobs-local` | S3 bucket where rendered PDFs are stored |
| `S3_PRESIGNED_URL_EXPIRY` | `3600` | Validity of the S3 presigned URL stored in DynamoDB as `pdf_url`, in seconds |
| `VIEWER_URL_MAP_RASTER` | — | Webmapviewer endpoint for raster map printing (**required**) |
| `VIEWER_URL_MAP` | — | Webmapviewer endpoint for vector-tile map printing |
| `VIEWER_URL_LEGEND` | — | Webmapviewer endpoint for legend printing |
| `VECTOR_TILES` | `false` | Set to `true` to use the vector-tile viewer URL instead of the raster one |
| `TIMEOUT_LOADING_WEB_PAGE` | `30000` | Browser page-load timeout in milliseconds |
| `ROUND_UP_TO_NEXT_Z_INT` | `true` | Round the interpolated zoom level up to the next z (integer) for sharper raster tiles |
| `GO_ONE_Z_FURTHER` | `false` | Use one zoom level higher than calculated (e.g. to force pk25 at scale 1:25 000) |
| `USE_GPU` | `false` | Set to `true` to use the local machine's GPU (native OpenGL) instead of the SwiftShader software rasterizer — for local development only |

### Kubernetes probes

The worker writes probe files to signal its state to Kubernetes:

| Probe | File (default) | Env var | Behaviour |
| ----- | -------------- | ------- | --------- |
| Startup | `/tmp/startup_probe` | `STARTUP_PROBE_FILE` | Created once when the worker starts; never removed |
| Liveness | `/tmp/liveness_probe` | `LIVENESS_PROBE_FILE` | Touched after every polling cycle; removed on graceful shutdown |

Configure the Kubernetes probes as `exec` checks:

```yaml
startupProbe:
  exec:
    command: ["test", "-f", "/tmp/startup_probe"]
livenessProbe:
  exec:
    command: ["test", "-f", "/tmp/liveness_probe"]
```

You can verify the probe files manually while the worker is running:

```bash
# startup probe — exists once the worker loop has started
test -f /tmp/startup_probe && echo "started" || echo "not started"

# liveness probe — touched every polling cycle
test -f /tmp/liveness_probe && echo "alive" || echo "not alive"
```

### OpenTelemetry (tracing)

| Env | Default | Description |
| --- | ------- | ----------- |
| `OTEL_SDK_DISABLED` | `false` | Set to `true` to disable all OTEL instrumentation |
| `OTEL_ENABLE_LOGGING` | `false` | Set to `true` to inject `otelTraceID` and `otelSpanID` into log records |
| `OTEL_ENABLE_BOTOCORE` | `false` | Set to `true` to enable tracing of DynamoDB, SQS, and S3 calls |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTLP gRPC endpoint of the collector |
| `OTEL_EXPORTER_OTLP_INSECURE` | `false` | Set to `true` to use an insecure (non-TLS) connection to the collector |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Optional headers for the OTLP collector (e.g. for authentication) |
| `OTEL_RESOURCE_ATTRIBUTES` | — | Resource attributes attached to all spans (e.g. `service.name=service-print-renderer`) |

#### Local tracing setup

To test tracing locally, start the OTEL collector and Zipkin:

```bash
docker compose -f docker-compose-otel.yml up -d
```

Then start the app with `make run`. Traces are visible at **<http://localhost:9411>** (Zipkin UI).

## Debugging

### WebGL renderer info

To verify that headless Chrome can access WebGL and report the expected renderer, run the worker with the `-i` / `--renderer-info` flag:

```bash
make renderer-info
# or directly: uv run python -m app.worker --renderer-info
```

This launches a headless Chrome instance, evaluates a WebGL probe, logs the hardware-acceleration status and the renderer name, then exits. No queue polling or AWS calls are made.
