# service-print — OTEL Metrics (GPS-694)

Handover notes for the metrics work on branch **`feat-GPS-694-otel-metrics`**, which spans two
repositories: [`service-print-api`](../service-print-api) and `service-print-renderer`.
Neither branch is merged yet, so everything below is still open to change.

> **TL;DR** — of the 11 metrics requested in GPS-694, **7 are delivered by these branches**:
> 6 from **4 custom instruments** plus 1 from **default instrumentation**. **2 more are specified
> but not yet available** — queue depth and dropped jobs come from the **queue infrastructure**
> (CloudWatch), not from our code, and wait on the ticket in §4. Cancellation and download counters
> are blocked on endpoints that do not exist yet.

---

## 1. Key design decisions

These are the non-obvious choices. If you read nothing else, read this.

**One logical service.** `service-print` is a single service made of two processes (the API and
the renderer). Both report `service.name="service-print"`, and *all* custom instruments live
under the single namespace `swissgeo.service_print.*`. They are told apart by `scope.name`
(the defining Python module), not by the metric name or the `job` label.

This is not a preference but the only form the ADD allows: its two permitted namespaces are
`swissgeo.<service_name>.<metric>` and `swissgeo.<metric>`, so the unit is the *service*.
Per-process namespaces (`swissgeo.service_print_api.*` / `…_renderer.*`) would require two
service names, contradicting the `service.name` we pin in §6. The cost is that the two processes
cannot be split by the Prometheus `job` label — use `otel_scope_name` for that.

**Default-first, and infrastructure before both.** Per the swissgeo metrics ADD, a custom metric is
only added when no default metric answers the question. We apply the same test one level lower:
if the *infrastructure* already publishes the number, we do not measure it ourselves either.
Request volume and status splits come from the FastAPI instrumentation's `http.server.request.duration`;
queue state comes from CloudWatch. What remains custom is only what is true inside our application
and nowhere else.

**Nothing about the queue is measured from inside the application.** Queue depth and dropped jobs
look like easy custom metrics and are not. A depth gauge sampled inside the API only updates while
requests arrive, so it holds a stale value in exactly the situations worth alerting on: no traffic,
or a renderer that has stopped consuming. A drop counter in the renderer barely sees the drop —
SQS moves the message to the DLQ on its own, after the worker has already marked the job `error`
on its final attempt, so the counter fires only for the residue that bypassed that path. Both
numbers are properties of the queue, and the queue already publishes them.

**Attributes, not names.** One `jobs` counter with an `outcome` attribute, rather than one counter
per outcome. Adding a new outcome does not add a new metric name — `created` was added to the API
this way, without a new instrument.

**No unit tests for metric emission.** This follows the convention in the reference service
`service-portal-state`. The instrumented code paths are exercised by the existing endpoint and
worker tests.

**`scope.version`.** Each metrics module defines `METRICS_SCHEMA_VERSION` next to its meter, so a
schema change and its version bump land in the same diff. It stays at **`1.0.0`** in both services:
the removals described here happen *before* the branches merge, so no consumer ever saw a `1.x`
containing `queue.depth` or `outcome="dropped"`. There is nothing to break, and therefore nothing
to bump.

---

## 2. Metrics overview

Mapping of every metric requested in GPS-694 to what now exists. **Source** is one of
*Custom* (an instrument we define), *Default* (existing instrumentation), or *Infrastructure*
(published by AWS, ingested by the observability platform — see §4).

**Status:** ✅ delivered by these branches · ⏳ specified, waiting on the infrastructure ticket
(§4) · ❌ blocked, see §7.

| # | Requested metric | Status | Source | Instrument / origin | Owner |
| --- | --- | --- | --- | --- | --- |
| 1 | Number of started print | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="started"}` | renderer |
| 2 | Number of print cancellation | ❌ | — | *no cancellation endpoint exists* | — |
| 3 | (Number of print download) | ❌ | — | *no download endpoint; per ADD this is business analytics → Athena / CloudFront logs, not a metric* | — |
| 4 | Number of print success | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="success"}` | renderer |
| 5 | Number of print error | ✅ | **Custom** | `swissgeo.service_print.jobs` `{outcome="error"}` | renderer |
| 6 | Number of get print status | ✅ | **Default** | `http.server.request.duration` count, `http.route="/jobs/{job_id}"` | api |
| 7 | Number of jobs in the queue | ⏳ | **Infrastructure** | `AWS/SQS` `ApproximateNumberOfMessagesVisible` (jobs queue) | infra |
| 8 | Jobs dropped from queue / timeout (GPS-660) | ⏳ | **Infrastructure** | `AWS/SQS` `NumberOfMessagesDeleted` (DLQ) | infra |
| 9 | Job processing duration (no queue wait) | ✅ | **Custom** | `swissgeo.service_print.job.processing.duration` | renderer |
| 10 | Job waiting time (in queue) | ✅ | **Custom** | `swissgeo.service_print.job.wait.duration` | renderer |
| 11 | Print duration | ✅ | **Custom** | `swissgeo.service_print.job.total.duration` | renderer |

Beyond the ticket, the API also emits `swissgeo.service_print.jobs` `{outcome="created"}` — a job
accepted and enqueued. It closes the lifecycle at the front: every job now counts once at creation
and once at pickup, so the two can be compared as rates.

Note on #1: *"started print"* has two readings. The custom counter measures a job the **renderer**
began processing. If you mean *"a print was requested"* (`POST /jobs` volume), that is **Default** —
`http.server.request.duration` on route `/jobs`, where `202` = newly queued and `200` = deduplicated.
Neither is the same as `created`, which counts only enqueued jobs (no dedup hits, no rejections).

Note on #7 and #8: these are **not delivered by this branch**. They depend on the infrastructure
ticket in §4 landing. Until it does, the two metrics are unavailable — deliberately, in preference
to shipping the two flawed custom instruments they replace (§1).

---

## 3. The custom instruments — and their names

This section is the basis for the naming discussion. Four names, five definitions
(`jobs` is defined in both repos).

| Instrument | Type | Unit | Attributes | `scope.name` | Repo |
| --- | --- | --- | --- | --- | --- |
| `swissgeo.service_print.jobs` | Counter | `{job}` | `outcome` = `started` \| `success` \| `error` | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.jobs` | Counter | `{job}` | `outcome` = `created` | `app.core.metrics` | api |
| `swissgeo.service_print.job.processing.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.job.wait.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |
| `swissgeo.service_print.job.total.duration` | Histogram | `s` | – | `app.helpers.metrics` | renderer |

The `jobs` counter is the one instrument defined in **both** scopes: the API owns `created`, the
renderer owns the rest. OTEL permits this — the two are distinct streams that Prometheus merges
into one series family, told apart by `otel_scope_name`. Name, unit and description must stay
byte-identical across the two definitions, or Prometheus sees conflicting `HELP` text for a single
series. `sum by (outcome) (…)` drops the scope label and reunites them.

### Prometheus rendering

| OTEL instrument name | Prometheus series | Attributes (allowed values) |
| --- | --- | --- |
| `swissgeo.service_print.jobs` | `swissgeo_service_print_jobs_total` | `outcome` = `created` \| `started` \| `success` \| `error` |
| `swissgeo.service_print.job.processing.duration` | `swissgeo_service_print_job_processing_duration_seconds_bucket` / `_count` / `_sum` | – |
| `swissgeo.service_print.job.wait.duration` | `swissgeo_service_print_job_wait_duration_seconds_bucket` / `_count` / `_sum` | – |
| `swissgeo.service_print.job.total.duration` | `swissgeo_service_print_job_total_duration_seconds_bucket` / `_count` / `_sum` | – |

Labels carried by all of the above, from the resource and instrumentation scope:

| Label | Value |
| --- | --- |
| `job` | `service-print` (Prometheus' rendering of the `service.name` resource attribute) |
| `service_instance_id` / `instance` | the hostname, i.e. the pod name (§6) |
| `otel_scope_name` | `app.helpers.metrics` (renderer) or `app.core.metrics` (api) |
| `otel_scope_version` | `1.0.0` (`METRICS_SCHEMA_VERSION`) |

### Default metrics we rely on (not ours)

| OTEL instrument | Prometheus series | We use it for |
| --- | --- | --- |
| `http.server.request.duration` | `http_server_request_duration_seconds_{bucket,count,sum}` | get-print-status volume (`http.route="/jobs/{job_id}"`); `POST /jobs` volume and outcome split via `http.response.status_code` (202 queued, 200 duplicate, 503 overloaded, 500 error) |

### Name anatomy

All custom names decompose as `<root>` . `<service>` . `<sub-namespace…>` . `<leaf>`, lowercase,
`.` as the namespace delimiter and `_` only *within* a multi-word segment.

| Full name | Root | Service | Sub-namespace | Leaf |
| --- | --- | --- | --- | --- |
| `swissgeo.service_print.jobs` | `swissgeo` | `service_print` | — | `jobs` |
| `swissgeo.service_print.job.processing.duration` | `swissgeo` | `service_print` | `job.processing` | `duration` |
| `swissgeo.service_print.job.wait.duration` | `swissgeo` | `service_print` | `job.wait` | `duration` |
| `swissgeo.service_print.job.total.duration` | `swissgeo` | `service_print` | `job.total` | `duration` |

### Rules applied (from the ADD)

- Two namespace forms are permitted: `swissgeo.<service_name>.<metric>` when the metric only makes
  sense in one service, and `swissgeo.<metric>` when it only makes sense within the org. All four
  instruments here take the first; the service name's `-` becomes `_`
  (`service-print` → `service_print`).
- Lowercase; `.` separates namespaces; `_` only inside a single multi-word segment.
- Namespaces are never pluralised. A **leaf is pluralised only when it counts discrete
  instances** — hence `jobs` (a counter of jobs) but `duration` (a measurement).
- **No units in the name** — the unit lives in the instrument's `unit` field (`{job}`, `s`).
  Prometheus re-appends `_seconds` / `_total` on its own.
- **Varying dimensions are attributes, not names**: one `jobs` counter with `outcome`, rather
  than `jobs.started` / `jobs.success` / …
- Never reuse an OTEL semantic-convention namespace bare (`http.*`, `k8s.*`, `messaging.*`, …).
  Where one genuinely fits, the ADD's sanctioned form is to take that namespace and prefix it with
  `swissgeo.` — e.g. `swissgeo.messaging.*` for queue semantics. None of our four instruments
  needed this.

### Semantics worth knowing

- **`created`** is recorded by the API after `send_to_queue` succeeds, so it counts jobs the
  renderer will actually see. It skips the deduplicated re-request (HTTP 200, an existing job),
  the overload rejection (503) and a failed enqueue — none of which produce a new job. It is
  therefore *not* the same as `POST /jobs` request volume, which the default
  `http.server.request.duration` already gives you.
- **`started`** and **`job.wait.duration`** are recorded **once, on first pickup**
  (`receive_count <= 1`), so SQS redeliveries do not double-count.
- **`error`** is recorded only on the **final** failed attempt, when the job is marked `error` in
  DynamoDB — not on every retry. With no `dropped` counter (§1) this is now the single
  application-level failure counter.
- **`job.processing.duration`** is measured with `time.monotonic()` around `process_job`, i.e.
  render + S3 upload. It excludes queue wait.
- **`job.wait.duration`** derives from the SQS `SentTimestamp` message attribute (requested in
  `receive_messages`).
- **`job.total.duration`** is `now − created_timestamp_iso_8601`, i.e. GPS-694's *second* alternative
  (request → job successful). The "until PDF download" ideal would require downloads to route
  through the service. The created timestamp already ships in the SQS body, so no extra DynamoDB
  read is needed.

### Open questions for the naming discussion

1. **Singular/plural mix.** We have the leaf `jobs` *and* the sub-namespace `job.*`
   (`job.processing.duration`). They differ only by a plural `s`, which reads inconsistently
   even though it follows the rules literally. Options: rename the counter to something like
   `job.count` (but that smells of encoding the instrument type in the name), or accept it.
2. **The `outcome` attribute key.** The ADD permits short keys (`operation`, `outcome`, `format`)
   *"if registered centrally"*, otherwise they should be namespaced (`swissgeo.service_print.outcome`).
   Is `outcome` registered? If two services give it different value sets, we have a clash.
3. **How do the infrastructure metrics get named?** *(new — the open question that replaces
   "who owns `queue.depth`")* CloudWatch-sourced series will not arrive as `swissgeo.*`; their
   names depend entirely on the ingestion path chosen by infra. Three options, and this is a
   decision the team should make rather than inherit:
   - **Leave them under their AWS names.** Honest about provenance, matches whatever other
     services do with AWS metrics, but our queue signals then sit outside our namespace and are
     found by a different search than everything else in this document.
   - **Rename on ingest into `swissgeo.messaging.*`.** If the series are renamed at all, this is
     the form the ADD sanctions: queue depth and DLQ arrivals are messaging semantics, not
     service-print semantics, and the ADD's rule for a fitting OTEL convention namespace is to
     prefix it with `swissgeo.` rather than reuse it bare. It also stays honest — the queues
     belong to `service-print` today, but nothing about the *metric* does, so a later second
     consumer needs no rename.
   - **Rename on ingest into `swissgeo.service_print.queue.*`.** One consistent namespace on the
     dashboard, at the cost of a mapping that lives in the pipeline config rather than in our
     code — and of a name that claims to be ours while the semantics (and the caveats in §4) are
     AWS's. Note this asserts the metric only makes sense in this service, which is the ADD's
     test for the `swissgeo.<service_name>.*` form.

   Note that a rename cannot be complete: CloudWatch's only dimension is `QueueName`, so these
   series will never carry `service.name`, `otel_scope_name` or `instance` no matter what they are
   called. They will not join cleanly with the custom metrics in a single query.

---

## 4. What we need from infrastructure

Metrics #7 and #8 require SQS queue metrics to be available in the same place as our application
metrics. The requirements below are the content of the infrastructure ticket; the delivery
mechanism (metric streams, polling, a platform integration) is infra's choice and deliberately not
specified here.

### Queues in scope

Per environment, both queues used by `service-print`: the jobs queue (`SQS_QUEUE_NAME`) and its
dead-letter queue (`SQS_DL_QUEUE_NAME`).

| # | What we need to know | Queue | How to realize (`AWS/SQS` namespace) | Why |
| --- | --- | --- | --- | --- |
| 1 | Messages **waiting** to be picked up | jobs | `ApproximateNumberOfMessagesVisible` | Metric #7. Backlog; "is the renderer keeping up". |
| 2 | Messages **currently being processed** | jobs | `ApproximateNumberOfMessagesNotVisible` | In-flight work. Separates "busy" from "dead" when the backlog grows. |
| 3 | **Age of the oldest waiting message** | jobs | `ApproximateAgeOfOldestMessage` (s) — note ¹ | Keeps reporting when nothing is consumed, which is when `job.wait.duration` goes silent. |
| 4 | Messages **arriving** in the DLQ | DLQ | `NumberOfMessagesDeleted` — note ² | Metric #8. Jobs permanently given up on. |
| 5 | Messages **sitting** in the DLQ | DLQ | `ApproximateNumberOfMessagesVisible` — note ³ | Failed jobs accumulating unattended, i.e. the DLQ consumer has stopped. |
| 6 | *(nice to have)* Messages **entering and leaving** the jobs queue | jobs | `NumberOfMessagesSent`, `NumberOfMessagesDeleted` | Independent cross-check against `created` / `success`. Not blocking. |

**Note ¹ — `ApproximateAgeOfOldestMessage` has a documented blind spot.** On standard queues a
message received three or more times without being deleted is moved to the back of the queue and
excluded from this metric until processed. Our `SQS_MAX_RECEIVE_COUNT` is exactly 3, so jobs on
their final retry are invisible here. Read it alongside #1; do not build an SLO on it alone.

**Note ² — do not use `NumberOfMessagesSent` on the DLQ.** AWS counts only manual `SendMessage`
calls; messages moved automatically by the redrive policy are excluded, so the metric reads zero
for us. AWS recommends `ApproximateNumberOfMessagesVisible` for DLQ monitoring, but see note ³ —
since the renderer drains the DLQ, `NumberOfMessagesDeleted` is our reliable arrival count.

**Note ³ — the DLQ backlog is near zero by design.** `handle_dlq_message` consumes and deletes DLQ
messages to mark the jobs failed. A 1-minute sample of the DLQ's visible count will usually read 0
even while jobs are being dropped. A sustained non-zero value means the DLQ consumer itself has
stopped — worth alerting on, but a different condition from #4.

### Fidelity and placement

- 1-minute resolution is sufficient; end-to-end lag under ~5 minutes.
- Values must be reported **continuously**, independent of application traffic. This is the whole
  point of moving these metrics out of the application.
- Queryable and dashboard-able in the same place as our OTEL application metrics, so one dashboard
  can show backlog next to success rate.
- **Dimensions:** CloudWatch publishes SQS metrics with a single dimension, `QueueName`. There is
  no environment or service dimension. Environment separation therefore comes from the queue naming
  convention being preserved into the target system — preferably mapped to an explicit environment
  label during ingestion rather than parsed out of the queue name in every query.

---

## 5. Gotchas

- **Never read a counter's raw value.** It is a per-process cumulative total that resets to 0 when
  the process restarts. Always use `rate()` or `increase()`, which handle resets.
- **A counter series does not exist until incremented once.** An idle worker emits no
  `jobs_total` series at all — this is the usual reason a query returns nothing.
- **CloudWatch counters are not OTEL counters.** They arrive as per-interval sums, not monotonic
  cumulatives. `rate()` over them is wrong; aggregate them directly. This is one more reason the
  two sources do not mix in a single expression.
- **Duration histograms use the SDK's default bucket boundaries** (`0, 5, 10, 25, 50, …`), which
  are millisecond-oriented. Our durations are in **seconds**, so sub-second queue waits all land in
  the first bucket. `_count`, `_sum` and `max` are trustworthy; **`job.wait.duration` percentiles
  are not** until the buckets are tuned. Do not build an SLO on them yet. Tune with real data
  (via a `View`) rather than guessing now.
- **`otel_scope_name` only exists if Prometheus is told to keep it.** Its OTLP receiver drops the
  instrumentation scope by default; `prometheus.yml` now sets `otlp.promote_scope_metadata: true`.
  Without it there is no scope label at all, and since both processes share `job="service-print"`
  *and* define `swissgeo.service_print.jobs`, nothing distinguishes the API's `created` from the
  renderer's outcomes. Whatever runs Prometheus in the deployed environments needs the same
  setting, or the two collapse. Note that turning it on **changes the label set**, so it starts
  new series: old and new coexist until the old ones age out of the lookback window.
- **`instance` comes from the hostname, not from the SDK.** Both services set
  `service.instance.id` explicitly (§6), because the SDK either omits it (renderer, 1.39) or
  invents a fresh UUID per process start (api, 1.43) — the latter minting a new series on every
  deploy. Do not remove that code on an SDK bump, and do not run either process with forked
  workers without adding the pid: replicas sharing a label set corrupt `rate()`.
- **`created − started` is not the queue backlog**, however much it looks like one. The two are
  per-process cumulative counters that reset independently when the API and the renderer restart,
  and `increase()` extrapolates at window edges — the difference drifts and can go negative.
  Compare them as *rates* to answer "is the renderer keeping up"; read the backlog itself off
  the infrastructure metric (§4 #1).
- **`OTEL_METRIC_EXPORT_INTERVAL` / `_TIMEOUT` are read straight from `os.environ` by the OTEL
  SDK**, not through `settings.py`. In the renderer, `load_dotenv()` puts `.env` into the
  environment. In the API, Pydantic's `env_file=` does **not** — the `Makefile`'s
  `export UV_ENV_FILE` is what bridges it. Run the API outside `make` and the interval silently
  falls back to 60 s. Production is unaffected (k8s injects into `os.environ` directly).
- **The HTTP series exist only while `OTEL_ENABLE_FASTAPI=true`.**

---

## 6. `service.instance.id`

Both services set `service.instance.id` themselves, defaulting to the **hostname** — which is the
pod name under Kubernetes. No manifest change is required. This section records why, since the
reasoning is not obvious from the two lines of code it produced.

### The problem

Prometheus identifies a time series by its full label set. Every custom metric we emit carries
`job="service-print"` (from `service.name`) and, since the fix in `prometheus.yml`,
`otel_scope_name`. Nothing else. Two renderer pods therefore push **the same label set** for
`swissgeo.service_print.jobs{outcome="success"}`.

That is not a merge. Each pod keeps its own cumulative counter, starting at zero when it starts,
and both push into one series. Prometheus sees a value that jumps up and down as samples from the
two processes interleave — and rejects some outright as duplicate or out-of-order. `rate()` over
that series is meaningless: it reads each downward step as a counter reset. The same applies to
the histograms' `_count` and `_sum`.

This was latent only because the renderer runs a single pod. The API used to avoid it by accident,
not design (below).

### Why the SDK's own value is not the answer

`Resource.create()` on `opentelemetry-sdk` 1.43 populates `service.instance.id` with a **random
UUID generated at process start**; on 1.39, which the renderer pins, it does not. That was the
entire reason the API's series carried an `instance` label and the renderer's did not — the two
repos sit four releases apart. Verified against `target_info` in the local stack.

So upgrading the renderer's SDK would have produced an `instance` label, and would have been the
wrong fix. A fresh UUID per process start means **a new time series on every restart and every
deploy**, forever. Two `created` series were visible in the local Prometheus at one point,
differing only by UUID: that was a single API process having restarted once. Over a year of
deploys, unbounded series growth for a property we can set deliberately and keep bounded.

### What we do instead

`_build_resource()` in [app/helpers/otel.py](app/helpers/otel.py) (and `app/otel.py` in the API)
sets `service.instance.id` to `socket.gethostname()`. Under Kubernetes the container hostname *is*
the pod name, so this yields one bounded series per pod, reused across restarts of that pod.
Counter resets within a pod are then a genuine reset, which `rate()` and `increase()` handle.

Two properties worth keeping if this code is touched:

- **It only fills the gap.** If `OTEL_RESOURCE_ATTRIBUTES` already carries a `service.instance.id`,
  the fallback stands aside, so a deployment can still name instances explicitly (e.g. via the
  downward API). Attributes passed to `Resource.create()` *override* the environment rather than
  merge with it, so this cannot be expressed by passing the hostname unconditionally.
- **It assumes one process per pod.** True today: the renderer is a single worker loop and the API
  runs `uvicorn` with no `--workers`. Forked workers would share a hostname and collide with each
  other; adding `--workers` means adding the pid, or the metrics quietly go wrong again.

It follows that `service.name` cannot be set from the environment either — `otel.py` pins it to
`service-print` for both processes. `.env.default` in both repos used to set `service.name` inside
`OTEL_RESOURCE_ATTRIBUTES` (`service-print-renderer` / `service-print-api`); those values **never
took effect**, and read as though the two processes reported different service names. They are now
commented out, with the override syntax left as a hint.

### Consequences at rollout

Adding a label **changes the label set**, so the renderer's existing series stop receiving samples
and new ones begin. Queries that aggregate — `sum by (outcome) (rate(…))`, everything in the
READMEs — are unaffected. Anything pinned to a bare series will see a discontinuity. There is no
way to add the label without this; it is a one-time cost, cheaper now, before dashboards exist,
than after.

---

## 7. Not implemented, and why

| Metric | Blocker |
| --- | --- |
| **Print cancellation** | No cancellation endpoint exists anywhere in the API. Needs the feature first; it would then be a counter. |
| **Print download** | No download endpoint — clients fetch the PDF directly from S3/ingress, so the service never observes a download. Additionally the ADD classifies downloads as **business/usage analytics**, whose home is Athena over CloudFront access logs, *not* OTEL metrics. GPS-694 itself notes routing downloads through the service would add load. |

Both are product decisions, not instrumentation gaps.

---

## 8. Outstanding follow-ups

1. **Agree the naming** (§3, open questions 1–3). Question 3 — how the infrastructure-sourced
   metrics are named — is new and needs a decision before the infra ticket is implemented, not
   after.
2. **File and land the infrastructure ticket** (§4). Metrics #7 and #8 are unavailable until it
   does — this is the one gap the branches cannot close themselves.
3. **Kibana is the definition of done, not Prometheus** (ADD §6). Verify each metric reads
   correctly in Kibana's default time-series view — in particular that counters are shown as a
   *rate* and durations as *percentiles*.
4. **Build the queue/lifecycle dashboard**: success rate, backlog, DLQ arrivals, queue-wait vs
   processing percentiles. Listed as a follow-up in the ADD itself. Note it now spans two data
   sources that do not join on a common label (§3, question 3).
5. **Confirm the GPS-660 semantics.** Our #8 now counts DLQ arrivals, i.e. retry exhaustion. If
   GPS-660 means a specifically *time-based* expiry, that is a different condition and needs its
   own signal — most likely `ApproximateAgeOfOldestMessage` with a threshold, not a counter.
6. **Tune histogram buckets** once real production distributions are visible.
7. **Align the renderer's `opentelemetry-sdk` with the API's** (1.39.1 → 1.43.0). Optional:
   §6 removed the correctness reason for it. It needs `opentelemetry-instrumentation-botocore`
   to go `0.60b1` → `0.64b0` (the pin that actually holds the core back), which spans four
   instrumentation releases and may shift botocore's span attribute names. Own branch, own PR.

---

## 9. References

- Swissgeo *OpenTelemetry Metrics* Architecture Design Document (naming, `scope.*`, default-first,
  cardinality, instrument types, UCUM units).
- Reference implementation: `service-portal-state` — `app/core/metrics.py`, `app/otel.py`.
- OTEL metric naming: <https://opentelemetry.io/docs/specs/semconv/general/metrics/>
- Instrumentation scope: <https://opentelemetry.io/docs/concepts/instrumentation-scope/>
- Resource semantic conventions, `service.instance.id`:
  <https://opentelemetry.io/docs/specs/semconv/resource/#service>
- Available CloudWatch metrics for Amazon SQS:
  <https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html>
- OTEL messaging semantic conventions (**spans only** — there is no SQS metric convention, which is
  why #7 and #8 come from CloudWatch rather than from a standard instrument):
  <https://opentelemetry.io/docs/specs/semconv/messaging/sqs/>
