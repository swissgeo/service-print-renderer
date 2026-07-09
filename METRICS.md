# service-print — OTEL Metrics (GPS-694)

Handover notes for the metrics work on branch **`feat-GPS-694-otel-metrics`**, which spans two
repositories: [`service-print-api`](../service-print-api) and `service-print-renderer`.

> **TL;DR** — 9 of the 11 metrics requested in GPS-694 are delivered: **5 custom instruments**
> plus 2 signals taken from default instrumentation. Cancellation and download counters are
> blocked on endpoints that do not exist yet.

---

## 1. Key design decisions

These are the non-obvious choices. If you read nothing else, read this.

**One logical service.** `service-print` is a single service made of two processes (the API and
the renderer). Both report `service.name="service-print"`, and *all* custom instruments live
under the single namespace `swissgeo.service_print.*`. They are told apart by `scope.name`
(the defining Python module), not by the metric name or the `job` label.

**Default-first.** Per the swissgeo metrics ADD, a custom metric is only added when no default
metric can answer the question. Request volume and status splits for `POST /jobs` and
`GET /jobs/{job_id}` are therefore **not** custom metrics — the FastAPI instrumentation's
`http.server.duration` already carries `http.route` and `http.response.status_code`. The ADD
names "get print status" explicitly as a case the default covers.

**Attributes, not names.** One `jobs` counter with an `outcome` attribute, rather than four
counters. Adding a new outcome does not add a new metric name.

**No unit tests for metric emission.** This follows the convention in the reference service
`service-portal-state`. The instrumented code paths are exercised by the existing endpoint and
worker tests.

**`scope.version`.** Each metrics module defines `METRICS_SCHEMA_VERSION` next to its meter, so a
schema change and its version bump land in the same diff. Currently `1.0.0` in both services.

---

## 2. Metrics overview

Mapping of every metric requested in GPS-694 to what now exists.

| # | Requested metric | Status | Custom? | Instrument / source | Emitted by |
| --- | --- | --- | --- | --- | --- |
| 1 | Number of started print | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="started"}` | renderer |
| 2 | Number of print cancellation | ❌ | — | *no cancellation endpoint exists* | — |
| 3 | (Number of print download) | ❌ | — | *no download endpoint; per ADD this is business analytics → Athena / CloudFront logs, not a metric* | — |
| 4 | Number of print success | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="success"}` | renderer |
| 5 | Number of print error | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="error"}` | renderer |
| 6 | Number of get print status | ✅ | **Default** | `http.server.duration` count, `http.route="/jobs/{job_id}"` | api |
| 7 | Number of jobs in the queue | ✅ | **Custom** | `swissgeo.service_print.queue.depth` | api |
| 8 | Jobs dropped from queue / timeout (GPS-660) | ⚠️ | **Custom** | `swissgeo.service_print.jobs` `{outcome="dropped"}` | renderer |
| 9 | Job processing duration (no queue wait) | ✅ | **Custom** | `swissgeo.service_print.job.processing.duration` | renderer |
| 10 | Job waiting time (in queue) | ✅ | **Custom** | `swissgeo.service_print.job.wait.duration` | renderer |
| 11 | Print duration | ✅ | **Custom** | `swissgeo.service_print.print.duration` | renderer |

Note on #1: *"started print"* has two readings. The custom counter measures a job the **renderer**
began processing. If you mean *"a print was requested"* (`POST /jobs` volume), that is **Default** —
`http.server.duration` on route `/jobs`, where `202` = newly queued and `200` = deduplicated.

Note on #8: our `dropped` counter fires when a job reaches the DLQ after `SQS_MAX_RECEIVE_COUNT`
retries. **If GPS-660 means a specifically time-based expiry, this is a different condition** and
the counter may need adjusting. Unverified against that ticket.

### The 5 custom instruments

| Instrument | Type | Unit | Attributes | `scope.name` | Repo |
| --- | --- | --- | --- | --- | --- |
| `swissgeo.service_print.jobs` | Counter | `{job}` | `outcome` = `started` \| `success` \| `error` \| `dropped` | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.job.processing.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.job.wait.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.print.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.queue.depth` | Gauge | `{message}` | – | `app.core.metrics` | api |

### Semantics worth knowing

- **`started`** and **`job.wait.duration`** are recorded **once, on first pickup**
  (`receive_count <= 1`), so SQS redeliveries do not double-count.
- **`error`** is recorded only on the **final** failed attempt, when the job is marked `error` in
  DynamoDB — not on every retry.
- **`job.processing.duration`** is measured with `time.monotonic()` around `process_job`, i.e.
  render + S3 upload. It excludes queue wait.
- **`job.wait.duration`** derives from the SQS `SentTimestamp` message attribute (now requested in
  `receive_messages`).
- **`print.duration`** is `now − created_timestamp_iso_8601`, i.e. GPS-694's *second* alternative
  (request → job successful). The "until PDF download" ideal would require downloads to route
  through the service. The created timestamp already ships in the SQS body, so no extra DynamoDB
  read is needed.
- **`queue.depth`** piggybacks the `ApproximateNumberOfMessages` read that `is_queue_overloaded`
  already performs on `POST /jobs` — no extra AWS calls, but it only updates while print requests
  arrive.

---

## 3. Metric names — canonical reference

Every name we emit or rely on, spelled out. This is the basis for the naming-convention
discussion.

### Custom metrics (ours)

| OTEL instrument name | Prometheus series | Attributes (allowed values) |
| --- | --- | --- |
| `swissgeo.service_print.jobs` | `swissgeo_service_print_jobs_total` | `outcome` = `started` \| `success` \| `error` \| `dropped` |
| `swissgeo.service_print.job.processing.duration` | `swissgeo_service_print_job_processing_duration_seconds_bucket` / `_count` / `_sum` | – |
| `swissgeo.service_print.job.wait.duration` | `swissgeo_service_print_job_wait_duration_seconds_bucket` / `_count` / `_sum` | – |
| `swissgeo.service_print.print.duration` | `swissgeo_service_print_print_duration_seconds_bucket` / `_count` / `_sum` | – |
| `swissgeo.service_print.queue.depth` | `swissgeo_service_print_queue_depth` | – |

Labels carried by all of the above, from the resource and instrumentation scope:

| Label | Value |
| --- | --- |
| `job` | `service-print` (Prometheus' rendering of the `service.name` resource attribute) |
| `otel_scope_name` | `app.helpers.metrics` (renderer) or `app.core.metrics` (api) |
| `otel_scope_version` | `1.0.0` (`METRICS_SCHEMA_VERSION`) |

### Default metrics we rely on (not ours)

| OTEL instrument | Prometheus series | We use it for |
| --- | --- | --- |
| `http.server.duration` | `http_server_duration_seconds_{bucket,count,sum}` — **name varies by semconv version**, see Gotchas | get-print-status volume (`http.route="/jobs/{job_id}"`); `POST /jobs` volume and outcome split via `http.response.status_code` (202 queued, 200 duplicate, 503 overloaded, 500 error) |

### Name anatomy

All custom names decompose as `<root>` . `<service>` . `<sub-namespace…>` . `<leaf>`, lowercase,
`.` as the namespace delimiter and `_` only *within* a multi-word segment.

| Full name | Root | Service | Sub-namespace | Leaf |
| --- | --- | --- | --- | --- |
| `swissgeo.service_print.jobs` | `swissgeo` | `service_print` | — | `jobs` |
| `swissgeo.service_print.job.processing.duration` | `swissgeo` | `service_print` | `job.processing` | `duration` |
| `swissgeo.service_print.job.wait.duration` | `swissgeo` | `service_print` | `job.wait` | `duration` |
| `swissgeo.service_print.print.duration` | `swissgeo` | `service_print` | `print` | `duration` |
| `swissgeo.service_print.queue.depth` | `swissgeo` | `service_print` | `queue` | `depth` |

### Rules applied (from the ADD)

- Root namespace `swissgeo.<service_name>.*`; the service name's `-` becomes `_`
  (`service-print` → `service_print`).
- Lowercase; `.` separates namespaces; `_` only inside a single multi-word segment.
- Namespaces are never pluralised. A **leaf is pluralised only when it counts discrete
  instances** — hence `jobs` (a counter of jobs) but `duration` / `depth` (measurements).
- **No units in the name** — the unit lives in the instrument's `unit` field
  (`{job}`, `{message}`, `s`). Prometheus re-appends `_seconds` / `_total` on its own.
- **Varying dimensions are attributes, not names**: one `jobs` counter with `outcome`, rather
  than `jobs.started` / `jobs.success` / …
- Never prefix a custom name with an existing OTEL semantic-convention namespace
  (`http.*`, `k8s.*`, `messaging.*`, …).

### Open questions for the naming discussion

1. **Singular/plural mix.** We have the leaf `jobs` *and* the sub-namespace `job.*`
   (`job.processing.duration`). They differ only by a plural `s`, which reads inconsistently
   even though it follows the rules literally. Options: rename the counter to something like
   `job.count` (but that smells of encoding the instrument type in the name), or accept it.
2. **`print.duration` vs `job.*`.** The end-to-end timer sits under `print.*` while the other two
   durations sit under `job.*`. Is the end-to-end measure about a *print* or about a *job*?
   Alternatives: `job.total.duration`, `job.e2e.duration`.
3. **`job.wait.duration`.** Is `wait` the clearest segment? Alternatives: `job.queue.duration`,
   `job.queue.wait`, `job.waiting.duration`.
4. **The `outcome` attribute key.** The ADD permits short keys (`operation`, `outcome`, `format`)
   *"if registered centrally"*, otherwise they should be namespaced (`swissgeo.service_print.outcome`).
   Is `outcome` registered? If two services give it different value sets, we have a clash.
5. **One namespace vs per-process.** We chose `swissgeo.service_print.*` for both processes, with
   `otel_scope_name` distinguishing them. The alternative — `swissgeo.service_print_api.*` and
   `swissgeo.service_print_renderer.*` — was rejected because they are one logical service
   (`service.name="service-print"`). Worth confirming the team agrees, since it means you cannot
   split the two by the Prometheus `job` label.
6. **`queue.depth` ownership.** It is emitted by the API but describes a queue the renderer
   consumes. The name is service-scoped, not process-scoped, which is consistent with (5) — but
   worth a sanity check.

---

## 4. What changed, per repo

Both branches are `feat-GPS-694-otel-metrics`.

### service-print-renderer

| File | Change |
| --- | --- |
| `app/helpers/metrics.py` | **new** — the 4 instruments + `record_*` helpers + `METRICS_SCHEMA_VERSION` |
| `app/helpers/otel.py` | added `_setup_meter_provider()`; `initialize_otel()` now returns a 3-tuple and `shutdown_otel()` flushes the meter provider |
| `app/worker.py` | instrumentation in `handle_message` / `handle_dlq_message`; timing around `process_job` |
| `app/helpers/sqs_queue.py` | request the `SentTimestamp` attribute in `receive_messages` |
| `.env.default` | `OTEL_ENABLE_METRICS`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_METRIC_EXPORT_TIMEOUT` |
| `docker-compose-otel.yml`, `otel-local-config.yaml`, `prometheus.yml`, `Makefile` | local Prometheus |
| `README.md` | metrics table + example PromQL |

### service-print-api

| File | Change |
| --- | --- |
| `app/core/metrics.py` | **new** — the `queue.depth` gauge + `METRICS_SCHEMA_VERSION` |
| `app/core/sqs_queue.py` | record queue depth inside `is_queue_overloaded` |
| `app/settings.py` | `otel_enable_metrics` default flipped `False` → **`True`** |
| `docker-compose-otel.yml`, `otel-local-config.yaml`, `prometheus.yml`, `Makefile` | local Prometheus |
| `README.md` | metrics table + example PromQL |

The metrics SDK was already wired in the API's `app/otel.py` before this branch; only the
instrument and the default flip were needed. `app/api/jobs.py` is **unchanged** — the request
counters that briefly existed there were removed under the default-first rule.

---

## 5. Local development

The OTEL stack (collector, Jaeger, Prometheus) is **shared** between the two repos under the
`service-print-local-otel` compose project. The three files (`docker-compose-otel.yml`,
`otel-local-config.yaml`, `prometheus.yml`) are byte-identical in both, so `make start-otel` from
either repo brings up (or reuses) the same containers.

```bash
make start-otel     # collector :4317, Jaeger UI :16686, Prometheus UI :9090
make start-moto     # AWS mocks
make run            # the worker  (or `make serve` in the API)
make stop-otel
```

Prometheus has **no persistent volume** — `make stop-otel` wipes all samples.

Metrics reach Prometheus by OTLP **push** (the collector's `otlphttp/prometheus` exporter →
Prometheus' `--web.enable-otlp-receiver`), not by scraping. Export cadence is
`OTEL_METRIC_EXPORT_INTERVAL` (10 s locally, SDK default 60 s).

### Prometheus name translation

OTEL names are rewritten on ingest: `.` → `_`, counters gain `_total`, the `s` unit appends
`_seconds`, annotation units (`{job}`, `{message}`) are dropped, histograms expand into
`_bucket` / `_count` / `_sum`.

| OTEL instrument | Prometheus |
| --- | --- |
| `swissgeo.service_print.jobs` | `swissgeo_service_print_jobs_total` |
| `swissgeo.service_print.job.processing.duration` | `swissgeo_service_print_job_processing_duration_seconds_{bucket,count,sum}` |
| `swissgeo.service_print.job.wait.duration` | `swissgeo_service_print_job_wait_duration_seconds_{bucket,count,sum}` |
| `swissgeo.service_print.print.duration` | `swissgeo_service_print_print_duration_seconds_{bucket,count,sum}` |
| `swissgeo.service_print.queue.depth` | `swissgeo_service_print_queue_depth` |

Both services share the label `job="service-print"`. Use `otel_scope_name` to tell them apart.

```promql
# Throughput by outcome
sum by (outcome) (rate(swissgeo_service_print_jobs_total[5m]))

# Success rate over completed jobs
  sum(rate(swissgeo_service_print_jobs_total{outcome="success"}[5m]))
/ sum(rate(swissgeo_service_print_jobs_total{outcome=~"success|error|dropped"}[5m]))

# p95 render + upload time
histogram_quantile(0.95,
  sum by (le) (rate(swissgeo_service_print_job_processing_duration_seconds_bucket[5m])))

# Current queue depth
swissgeo_service_print_queue_depth
```

More examples in each repo's `README.md` (§ Observability → Metrics → Example queries).

---

## 6. Gotchas

- **Never read a counter's raw value.** It is a per-process cumulative total that resets to 0 when
  the process restarts. Always use `rate()` or `increase()`, which handle resets.
- **A counter series does not exist until incremented once.** An idle worker emits no
  `jobs_total` series at all — this is the usual reason a query returns nothing.
- **Duration histograms use the SDK's default bucket boundaries** (`0, 5, 10, 25, 50, …`), which
  are millisecond-oriented. Our durations are in **seconds**, so sub-second queue waits all land in
  the first bucket. `_count`, `_sum` and `max` are trustworthy; **`job.wait.duration` percentiles
  are not** until the buckets are tuned. Do not build an SLO on them yet. Tune with real data
  (via a `View`) rather than guessing now.
- **`queue.depth` goes stale without `POST /jobs` traffic.** CloudWatch remains the continuous
  source of truth for queue length.
- **`OTEL_METRIC_EXPORT_INTERVAL` / `_TIMEOUT` are read straight from `os.environ` by the OTEL
  SDK**, not through `settings.py`. In the renderer, `load_dotenv()` puts `.env` into the
  environment. In the API, Pydantic's `env_file=` does **not** — the `Makefile`'s
  `export UV_ENV_FILE` is what bridges it. Run the API outside `make` and the interval silently
  falls back to 60 s. Production is unaffected (k8s injects into `os.environ` directly).
- **The `http.server.duration` series name varies by instrumentation version** (older semconv:
  `http_server_duration_milliseconds_*`; newer: `http_server_request_duration_seconds_*`). Confirm
  in Prometheus before wiring a dashboard. These series exist only while `OTEL_ENABLE_FASTAPI=true`.

---

## 7. Not implemented, and why

| Metric | Blocker |
| --- | --- |
| **Print cancellation** | No cancellation endpoint exists anywhere in the API. Needs the feature first; it would then be a counter. |
| **Print download** | No download endpoint — clients fetch the PDF directly from S3/ingress, so the service never observes a download. Additionally the ADD classifies downloads as **business/usage analytics**, whose home is Athena over CloudFront access logs, *not* OTEL metrics. GPS-694 itself notes routing downloads through the service would add load. |

Both are product decisions, not instrumentation gaps.

---

## 8. Outstanding follow-ups

1. **Kibana is the definition of done, not Prometheus** (ADD §6). Verify each metric reads
   correctly in Kibana's default time-series view — in particular that counters are shown as a
   *rate* and durations as *percentiles*.
2. **Build the queue/lifecycle dashboard**: success rate, queue depth, drops (GPS-660),
   queue-wait vs processing percentiles. Listed as a follow-up in the ADD itself.
3. **Confirm the GPS-660 semantics** for the `dropped` outcome (see note on #8 above).
4. **Tune histogram buckets** once real production distributions are visible.
5. Consider whether `queue.depth` should become an **observable gauge** polled on the collection
   interval, rather than sampled on `POST /jobs`.

---

## 9. References

- Swissgeo *OpenTelemetry Metrics* Architecture Design Document (naming, `scope.*`, default-first,
  cardinality, instrument types, UCUM units).
- Reference implementation: `service-portal-state` — `app/core/metrics.py`, `app/otel.py`.
- OTEL metric naming: <https://opentelemetry.io/docs/specs/semconv/general/metrics/>
- Instrumentation scope: <https://opentelemetry.io/docs/concepts/instrumentation-scope/>
