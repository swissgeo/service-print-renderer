# service-print-renderer


| Branch | Status |
|--------|-----------|
| develop | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=develop) |
| main | ![Build Status](https://codebuild.eu-central-1.amazonaws.com/badges?uuid=eyJlbmNyeXB0ZWREYXRhIjoiWGY0bjI5RG1FWGtZQzE3b1NZekdhMmplK3dYMVlUdzNxaERBSGdTTFhIcVhQVXp2VkhDZDFHTXRnbXVTQ2M2MkNnZTBackwwWnV0SlgrK3UxTXRoa2xBPSIsIml2UGFyYW1ldGVyU3BlYyI6InlaY3dib3pneE1mUzl4UWsiLCJtYXRlcmlhbFNldFNlcmlhbCI6MX0%3D&branch=main) |

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Summary Of The Project](#summary-of-the-project)
- [Deployment configuration](#deployment-configuration)
  - [OpenTelemetry (tracing)](#opentelemetry-tracing)
    - [Local tracing setup](#local-tracing-setup)

## Summary Of The Project

`service-print-renderer` is a background worker service responsible for consuming print jobs from an SQS queue and rendering them into PDF documents.

When `service-print-api` receives a print request from a client, it enqueues a job to SQS and returns a job ID. The renderer continuously polls that queue, picks up pending jobs one at a time, performs the PDF rendering, and updates the job status in DynamoDB accordingly. Clients can then query `service-print-api` with the job ID to check the status and retrieve the resulting document once it is ready.

## Deployment configuration

The service is configured by Environment Variable:

| Env | Default | Description |
| --- | ------- | ----------- |
| AWS_LOCAL | `false` | Set to `true` to point AWS clients at LocalStack instead of real AWS |
| LOCALSTACK_ENDPOINT | `http://localhost:4566` | Endpoint URL of the LocalStack instance used in local development |
| DYNAMODB_TABLE_NAME | `service-print-jobs-local` | The name of the DynamoDB table storing print job info |
| SQS_QUEUE_NAME | `service-print-jobs-queue-local` | The name of the SQS queue |
| SQS_WAIT_TIME_SECONDS | `20` | Long-polling wait time in seconds when reading from SQS |
| SQS_MAX_MESSAGES | `1` | Maximum number of messages to retrieve per SQS poll |
| AWS_CONNECT_TIMEOUT | `5` | Timeout in seconds for establishing a connection to DynamoDB/SQS/S3 |
| AWS_READ_TIMEOUT | `30` | Timeout in seconds for reading a response from DynamoDB/SQS/S3 |
| S3_BUCKET_NAME | `service-print-jobs-local` | S3 bucket where rendered PDFs are stored |
| VIEWER_URL_MAP_RASTER | - | Webmapviewer endpoint for raster map printing |
| VIEWER_URL_MAP | - | Webmapviewer endpoint for vector-tile map printing |
| VIEWER_URL_LEGEND | - | Webmapviewer endpoint for legend printing |
| VECTOR_TILES | `false` | Set to `true` to use the vector-tile viewer URL instead of the raster one |
| TIMEOUT_LOADING_WEB_PAGE | `30000` | Browser page-load timeout in milliseconds |
| ROUND_UP_TO_NEXT_Z_INT | `true` | Round the interpolated zoom level up to the next integer for better raster quality |
| GO_ONE_Z_FURTHER | `false` | Use one zoom level higher than calculated (e.g. to force pk25 at scale 25000) |

### OpenTelemetry (tracing)

| Env | Default | Description |
| --- | ------- | ----------- |
| OTEL_SDK_DISABLED | `false` | Set to `true` to disable all OTEL instrumentation |
| OTEL_ENABLE_LOGGING | `false` | Set to `true` to inject `otelTraceID` and `otelSpanID` into log records |
| OTEL_ENABLE_BOTOCORE | `false` | Set to `true` to enable tracing of DynamoDB and SQS calls |
| OTEL_EXPORTER_OTLP_ENDPOINT | `http://localhost:4317` | OTLP gRPC endpoint of the collector |
| OTEL_EXPORTER_OTLP_INSECURE | `false` | Set to `true` to use an insecure (non-TLS) connection to the collector |
| OTEL_EXPORTER_OTLP_HEADERS | - | Optional headers to send to the OTLP collector (e.g. for authentication) |
| OTEL_RESOURCE_ATTRIBUTES | - | Resource attributes attached to all spans (e.g. `service.name=service-print-renderer`) |

#### Local tracing setup

To test tracing locally, start the OTEL collector and Zipkin:

```bash
docker compose -f docker-compose-otel.yml up -d
```

Then start the app with `make run`. Traces are visible at **<http://localhost:9411>** (Zipkin UI).
