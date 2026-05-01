# Data Architecture — Ecommerce Pipeline

This document is the response to `docs/data_architecture_design_prompt.md`. Every section
maps 1:1 to the prompt's `<output_format>` schema. Non-obvious decisions are tagged
`[WHY]`.

**Data quality model.** Validation is declarative: each post-clean dataset has a JSON
spec in `validations/<name>.json` listing rule types (`column_exists`, `not_null`,
`unique`, `between`, `in_set`, `matches_strftime`, `matches_regex`). A small
pandas-based runner in `src/common/data_quality.py` reads the spec and applies the
rules. Bad rows are not dropped silently — they are quarantined into an `error_events`
table with a stable `reason` code and the original payload, then exposed through the
API. The post-clean rule-set still acts as a fail-fast gate: if it fails, the stage
aborts (it would mean the pre-filter and the spec have drifted).

> Earlier revisions of this doc described a Great Expectations-based pipeline. GX was
> removed on 2026-05-01 — see `prompts.md` for the rationale.

---

## <project_structure>

```
ecommerce_data_pipeline/
├── docs/
│   ├── data_architecture_design_prompt.md   # the prompt that produced this doc
│   └── data_architecture.md                 # this file
├── raw_data/
│   ├── customers.csv                        # source: customers (immutable input)
│   ├── orders.json                          # source: orders (immutable input)
│   └── events.jsonl                         # source: events (immutable input)
├── data/
│   └── warehouse.sqlite                     # generated SQLite warehouse (gitignored)
├── sql/
│   └── schema.sql                           # canonical CREATE TABLE statements
├── validations/                             # declarative DQ specs (one per dataset)
│   ├── customers.json
│   ├── orders_clean.json
│   ├── events.json
│   └── exchange_rates.json
├── src/
│   ├── common/
│   │   ├── config.py                        # paths, base currency, API URL/key from env
│   │   ├── logging.py                       # JSON logger; silences httpx/httpcore/urllib3
│   │   ├── db.py                            # SQLite connect (check_same_thread=False) + bootstrap
│   │   ├── data_quality.py                  # rule dispatcher: JSON spec → pandas predicates
│   │   └── exchange_rate_client.py          # exchangerate-api.com client with retry + timeout
│   ├── pipeline/
│   │   ├── ingest_customers.py              # stage 1
│   │   ├── ingest_orders.py                 # stage 2 (writes to staging_orders)
│   │   ├── ingest_events.py                 # stage 3
│   │   ├── enrich_exchange_rates.py         # stage 4
│   │   ├── load_warehouse.py                # stage 5 (staging → final orders)
│   │   └── run.py                           # orchestrator: runs all 5 stages in order
│   └── api/
│       ├── main.py                          # FastAPI app factory; /healthz
│       ├── deps.py                          # DB connection dependency
│       ├── schemas.py                       # Pydantic response models
│       └── routers/
│           ├── customers.py                 # GET /customers
│           ├── orders.py                    # GET /orders
│           ├── metrics.py                   # GET /metrics
│           ├── data_quality.py              # GET /data-quality (run summary + error counts)
│           └── error_events.py              # GET /error-events (paginated drill-in)
├── tests/
│   ├── conftest.py                          # tmp sqlite, validations dir, fake exchange client
│   ├── unit/
│   │   ├── test_expectation_suites.py       # asserts every spec references real schema columns
│   │   └── …
│   └── integration/
│       ├── test_pipeline_end_to_end.py      # runs full pipeline on fixture data
│       └── test_api.py                      # FastAPI TestClient against seeded DB
├── .github/workflows/
│   └── ci.yml                               # lint → test → build → pipeline → api-smoke → publish-image
├── Dockerfile                               # single image; CMD runs pipeline then uvicorn
├── docker-compose.yml                       # `pipeline` (one-shot) and `api` (long-running)
├── Makefile                                 # local entrypoints; mirrors CI commands
├── pyproject.toml                           # deps + ruff/pytest config
├── .env.example                             # EXCHANGE_RATE_API_URL, EXCHANGE_RATE_API_KEY, …
├── .dockerignore
├── .gitignore                               # excludes data/*.sqlite, .venv, etc.
├── prompts.md                               # decision log (chronological, per CLAUDE.md)
└── README.md                                # run instructions
```

[WHY] **Single Docker image** for pipeline + API: they share dependencies and the
challenge requires both run in Docker. Two images would duplicate the dep tree without
isolating any meaningful boundary. The image's `CMD` runs the pipeline once, *then*
exec's uvicorn — so an ephemeral host (Render free tier) gets a populated warehouse on
every cold start.

[WHY] **`staging_orders` table** between `ingest_orders` and `load_warehouse`: orders
ingestion and exchange-rate enrichment are separate stages and must each be
independently re-runnable. A staging table makes the hand-off durable and inspectable.

[WHY] **`validations/` not `gx/`**: the rules are six pandas predicates on tiny
dataframes; a 80-dep DQ framework was net cost, not benefit. JSON specs stay
git-tracked and human-readable.

---

## <data_quality_decisions>

The **Decision** column states the runtime behavior; the **Rule(s)** column names the
validation rule type that enforces it. "Quarantine" means the row is inserted into
`error_events` (with `reason`, `source_record_id`, `raw_payload`) and excluded from the
warehouse — never silently dropped.

| Issue | Source | Decision | Justification | Rule(s) |
|---|---|---|---|---|
| Duplicate row for `customer_id=3` | customers.csv | **Quarantine** the second occurrence (`reason=customer_id_duplicate`); keep first | PK uniqueness must hold; the duplicate is visible in `error_events` for audit | `unique("customer_id")` |
| Missing `name` (`customer_id=5`) | customers.csv | **Keep**, store NULL | Email is the recoverable identifier; dropping breaks order joins | `not_null("email")` *(name not asserted non-null)* |
| Missing `country` (`customer_id=6`) | customers.csv | **Keep**, store NULL | Country only affects per-country metrics; orders for this customer remain valid | *(no rule on country; aggregations exclude NULL)* |
| `customer_id` is `null` (`O1003`) | orders.json | **Quarantine** (`reason=customer_id_null`) | Every analytical query is per-customer; an unattributed order pollutes joins | `not_null("customer_id")` |
| Orphaned `customer_id=99` (`O1005`, `E4`) | orders.json, events.jsonl | **Quarantine** (`reason=customer_id_orphan`) | No joinable customer; aggregations are undefined | *(referential integrity enforced via FK + pre-filter)* |
| Negative `amount=-50.00` (`O1004`) | orders.json | **Quarantine** (`reason=amount_negative_or_invalid`) | The schema has no refund/credit type; treating negatives as revenue is wrong, treating as refunds invents semantics | `between("amount_original", min=0)` |
| Mixed-case `status` | orders.json | **Normalize** to lowercase on ingest | `GROUP BY status` requires consistent casing; lowercase is the least-surprise convention | `in_set("status", ["completed","cancelled"])` |
| Two date formats (`YYYY-MM-DD`, `DD-MM-YYYY`) | orders.json | **Parse both**, store ISO; unparseable rows quarantined (`reason=date_invalid`) | Single canonical format enables lexicographic ordering and SQLite date functions | `matches_strftime("order_date", "%Y-%m-%d")` |
| Mixed currencies (BRL/USD/EUR) | orders.json | **Preserve original** + add `amount_usd` and `exchange_rate` columns | Auditability: enrichment must be reversible | `matches_regex("currency_original", "^[A-Z]{3}$")` |
| Mixed `event_type` casing (`login`/`LOG_IN`) | events.jsonl | **Normalize**: lowercase + strip underscores → both → `login` | Funnel analysis requires a single canonical token | `in_set("event_type", ["login","purchase","logout","signup"])` |
| Invalid timestamp `"invalid_timestamp"` (`E6`) | events.jsonl | **Quarantine** (`reason=timestamp_invalid`) | An event with no time has no place in a funnel; imputation would fabricate | `matches_strftime("event_timestamp", "%Y-%m-%dT%H:%M:%SZ")` |
| Exchange rate fetched but `<= 0` or non-numeric | API response | **Abort enrichment** stage with ERROR | A non-positive rate would corrupt every USD conversion | `between("rate_to_usd", min=0, strict_min=true)` |

[WHY] **Quarantine over rejection**: dropped rows used to be invisible outside log
lines. Quarantine makes data-quality issues queryable, countable, and exposed through
the API (`/data-quality.error_events_summary`, `/error-events`). The warehouse contract
is unchanged — only clean rows reach it.

[WHY] **First-failing-reason wins per row**: a row with multiple defects (orphan
customer + bad date) produces one `error_events` entry, not many. Otherwise rejection
counts inflate and the same row appears under multiple reasons, complicating
dashboards. The order of pre-filter checks defines the de-facto reason priority.

[WHY] **Reason codes are stable, machine-readable strings** (`customer_id_orphan`,
`amount_negative_or_invalid`, …) — not human prose. Dashboards group by `reason`;
humans read the code.

---

## <data_model>

```sql
-- sql/schema.sql

CREATE TABLE IF NOT EXISTS customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT,                          -- nullable: source allows missing
    email        TEXT NOT NULL,
    country      TEXT,                          -- nullable: ISO-2 when present
    created_at   TEXT NOT NULL                  -- ISO YYYY-MM-DD
);
CREATE INDEX IF NOT EXISTS idx_customers_country ON customers(country);

CREATE TABLE IF NOT EXISTS exchange_rates (
    currency     TEXT PRIMARY KEY,              -- ISO-4217, e.g. "BRL"
    rate_to_usd  REAL NOT NULL,                 -- 1 unit of `currency` = rate_to_usd USD
    fetched_at   TEXT NOT NULL                  -- ISO-8601 UTC
);

CREATE TABLE IF NOT EXISTS orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    amount_original   REAL NOT NULL,
    currency_original TEXT NOT NULL,
    exchange_rate     REAL NOT NULL,            -- copied from exchange_rates at load time
    amount_usd        REAL NOT NULL,            -- amount_original * exchange_rate
    status            TEXT NOT NULL,            -- normalized lowercase
    order_date        TEXT NOT NULL,            -- ISO YYYY-MM-DD
    FOREIGN KEY (customer_id)       REFERENCES customers(customer_id),
    FOREIGN KEY (currency_original) REFERENCES exchange_rates(currency)
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date     ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);

CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    event_type      TEXT NOT NULL,              -- normalized lowercase, no underscores
    event_timestamp TEXT NOT NULL,              -- ISO-8601 UTC
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
CREATE INDEX IF NOT EXISTS idx_events_customer ON events(customer_id);
CREATE INDEX IF NOT EXISTS idx_events_type     ON events(event_type);

-- Staging table used between ingest_orders and load_warehouse.
-- Truncated at the start of ingest_orders and at the end of load_warehouse.
CREATE TABLE IF NOT EXISTS staging_orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    amount_original   REAL NOT NULL,
    currency_original TEXT NOT NULL,
    status            TEXT NOT NULL,
    order_date        TEXT NOT NULL
);

-- One row per (run_id, stage). Written after the rule-set runs at the end of each stage.
CREATE TABLE IF NOT EXISTS data_quality_runs (
    run_id       TEXT NOT NULL,                 -- pipeline run UUID
    stage        TEXT NOT NULL,                 -- e.g. "ingest_orders"
    checkpoint   TEXT NOT NULL,                 -- rule-set name (e.g. "orders_clean_checkpoint")
    success      INTEGER NOT NULL,              -- 1 or 0
    evaluated    INTEGER NOT NULL,              -- # rules evaluated
    succeeded    INTEGER NOT NULL,              -- # rules succeeded
    started_at   TEXT NOT NULL,                 -- ISO-8601 UTC
    duration_ms  INTEGER NOT NULL,
    PRIMARY KEY (run_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_dq_started ON data_quality_runs(started_at DESC);

-- Quarantine table for any row a pre-filter rejected.
CREATE TABLE IF NOT EXISTS error_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT NOT NULL,
    stage             TEXT NOT NULL,            -- ingest_customers / ingest_orders / ingest_events
    source_record_id  TEXT,                     -- order_id / event_id / customer_id (nullable)
    reason            TEXT NOT NULL,            -- machine-readable code
    raw_payload       TEXT,                     -- JSON of the original row
    occurred_at       TEXT NOT NULL             -- ISO-8601 UTC
);
CREATE INDEX IF NOT EXISTS idx_error_events_run    ON error_events(run_id);
CREATE INDEX IF NOT EXISTS idx_error_events_stage  ON error_events(stage);
CREATE INDEX IF NOT EXISTS idx_error_events_reason ON error_events(reason);
```

**Analytical query coverage** (all use indexed columns, no raw-text joins):

```sql
-- 1) Total revenue per customer in USD
SELECT customer_id, SUM(amount_usd) AS revenue_usd
FROM orders
WHERE status = 'completed'
GROUP BY customer_id;

-- 2) Order count and average amount per country
SELECT c.country,
       COUNT(o.order_id)        AS order_count,
       AVG(o.amount_usd)        AS avg_amount_usd
FROM orders o
JOIN customers c USING (customer_id)
WHERE c.country IS NOT NULL
GROUP BY c.country;

-- 3) Event funnel (login → purchase) per customer
SELECT customer_id,
       SUM(CASE WHEN event_type = 'login'    THEN 1 ELSE 0 END) AS logins,
       SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
FROM events
GROUP BY customer_id;
```

[WHY] **`exchange_rate` and `amount_usd` denormalized into `orders`**: queries are
read-mostly and analysts shouldn't have to join `exchange_rates` to get USD totals. The
rate is captured at load time, so historical orders keep the rate that was used.

[WHY] **`error_events` is one generic table, not per-stage tables**: keeps the API
endpoint and summary query trivial; stages just write their own `stage` value.
`raw_payload` is JSON-encoded TEXT so analysts can recover the original row without
joining back to source files.

---

## <pipeline_stages>

Each stage follows the same shape: **load → transform → pre-filter (with quarantine) →
post-clean rule-set (gate) → write**. The post-clean rule-set should always pass once
the pre-filter has run; a failure means filter and rules have drifted.

| Stage | Input | Output | Key transformations | Rule-set | Error behavior |
|---|---|---|---|---|---|
| **ingest_customers** | `raw_data/customers.csv` | `customers` table | Drop duplicate `customer_id`s (keep first); coerce types; preserve NULL `name`/`country` | `customers` | Duplicates → `error_events(reason=customer_id_duplicate)`. Rule-set fail → ERROR + abort. Idempotent: `INSERT OR REPLACE` on PK. |
| **ingest_orders** | `raw_data/orders.json` | `staging_orders` table | Lowercase `status`; parse both date formats to ISO; quarantine rows with null/orphaned `customer_id`, negative `amount`, or unparseable date | `orders_clean` | Truncates `staging_orders` first. Per-row rejects → `error_events`. Rule-set fail → ERROR + abort. |
| **ingest_events** | `raw_data/events.jsonl` | `events` table | Normalize `event_type` (lowercase, strip `_`); parse ISO timestamp; quarantine unparseable timestamps and orphaned `customer_id` | `events` | Per-line JSON failure → `error_events(reason=json_parse_error)`. Idempotent: `INSERT OR REPLACE` on `event_id`. |
| **enrich_exchange_rates** | distinct `currency_original` from `staging_orders` | `exchange_rates` table | Fetch USD rate per currency; build DataFrame `(currency, rate_to_usd, fetched_at)` | `exchange_rates` | API timeout → retry up to 3× with exponential backoff. Persistent failure or rule-set fail → ERROR + abort. Idempotent: `INSERT OR REPLACE` on `currency`. |
| **load_warehouse** | `staging_orders` ⨝ `exchange_rates` | `orders` table | Inner-join staging to rates; compute `amount_usd`; copy `rate_to_usd` into `exchange_rate` | *(no rule-set — relies on `orders_clean` and FK constraints)* | Missing rate for a staged currency → ERROR + abort. Idempotent: `INSERT OR REPLACE`; staging truncated at end. |

**After each stage:**
1. Writes a row into `data_quality_runs` (run_id, stage, success, counts, duration).
2. Emits a structured log line including the `validation_id`.
3. On rule-set failure, raises and the orchestrator aborts the pipeline with non-zero
   exit. Quarantine inserts have already been committed at this point, so forensic data
   survives even when the gate aborts.

[WHY] **No rule-set on `load_warehouse`**: the data was already validated in
`ingest_orders` and only joined here; SQLite FK constraints catch any drift.

[WHY] **Quarantine inserts commit before the gate fail**: useful for forensics — when
drift between pre-filter and rule-set causes the gate to abort, the offending rows are
still queryable via `/error-events`.

---

## <api_contract>

All endpoints return JSON. List endpoints use `limit` (default 100, max 500) and
`offset` (default 0).

### `GET /healthz`

Liveness probe. Returns `{"status": "ok"}`.

### `GET /customers`

Query params: `country` (optional ISO-2), `limit`, `offset`.

```python
class Customer(BaseModel):
    customer_id: int
    name: Optional[str]
    email: str
    country: Optional[str]
    created_at: date

class CustomerListResponse(BaseModel):
    items: list[Customer]
    total: int
    limit: int
    offset: int
```

### `GET /orders`

Query params: `customer_id` (optional int), `status` (optional), `currency` (optional ISO-4217), `limit`, `offset`.

```python
class Order(BaseModel):
    order_id: str
    customer_id: int
    amount_original: float
    currency_original: str
    exchange_rate: float
    amount_usd: float
    status: Literal["completed", "cancelled"]
    order_date: date

class OrderListResponse(BaseModel):
    items: list[Order]
    total: int
    limit: int
    offset: int
```

### `GET /metrics`

No query params. Returns the three analytical aggregates.

```python
class RevenuePerCustomer(BaseModel):
    customer_id: int
    revenue_usd: float

class CountryStats(BaseModel):
    country: str
    order_count: int
    avg_amount_usd: float

class FunnelEntry(BaseModel):
    customer_id: int
    logins: int
    purchases: int

class MetricsResponse(BaseModel):
    revenue_per_customer: list[RevenuePerCustomer]
    country_stats: list[CountryStats]
    event_funnel: list[FunnelEntry]
```

### `GET /data-quality`

No query params. Returns the latest pipeline run's per-stage rule-set summary plus
quarantine counts.

```python
class DataQualityRun(BaseModel):
    stage: str
    checkpoint: str
    success: bool
    evaluated: int
    succeeded: int
    started_at: datetime
    duration_ms: int

class ErrorEventSummary(BaseModel):
    stage: str
    reason: str
    count: int

class DataQualityResponse(BaseModel):
    run_id: str | None
    overall_success: bool
    stages: list[DataQualityRun]
    error_events_summary: list[ErrorEventSummary]
```

### `GET /error-events`

Paginated drill-in. Query params: `run_id` (optional), `stage` (optional),
`reason` (optional), `limit`, `offset`.

```python
class ErrorEvent(BaseModel):
    id: int
    run_id: str
    stage: str
    source_record_id: str | None
    reason: str
    raw_payload: str | None
    occurred_at: datetime

class ErrorEventListResponse(BaseModel):
    items: list[ErrorEvent]
    total: int
    limit: int
    offset: int
```

[WHY] **`/data-quality` summary + `/error-events` drill-in (two endpoints, not one)**:
analysts and dashboards want the summary in a single round-trip; engineers debugging a
specific row want pagination and filters. Different access patterns, different
endpoints.

[WHY] **One `/metrics` endpoint** for all three aggregates: analysts pull dashboard
data in one call. Splitting later is trivial; merging later would be a breaking change.

---

## <cicd_pipeline>

`.github/workflows/ci.yml` — six jobs, each runs the same command available locally
via `make`. Workflow-level `env:` block forwards `EXCHANGE_RATE_API_KEY` (from
`secrets`) and `EXCHANGE_RATE_API_URL` (literal) to every job.

| # | Job | Command | What it produces / validates |
|---|---|---|---|
| 1 | **lint** | `make lint` (`ruff check . && ruff format --check .`) | Validates style. Fails on style violations. |
| 2 | **test** | `make test` (`pytest tests/`) | Runs unit + integration tests, including `test_expectation_suites.py` which asserts every JSON spec references real schema columns. |
| 3 | **build** | `make build` (`docker compose build`) | Produces the runtime image. Cached via GHA Docker layer cache. |
| 4 | **pipeline** | `make pipeline` (`docker compose run --rm pipeline`) | Runs the full pipeline against committed fixture data. Asserts every rule-set succeeded and `SELECT COUNT(*) FROM orders > 0`. |
| 5 | **api-smoke** | `make api-smoke` (`docker compose up -d --wait api`, then curl `/healthz`, `/data-quality`, `/customers?limit=1`) | Validates the API boots (compose healthcheck) and `/data-quality` returns `overall_success: true`. |
| 6 | **publish-image** | `docker buildx` → push to GHCR. Gated on `needs: [pipeline, api-smoke]` and `if: github.ref == 'refs/heads/master'`. | Tags: `:${{ github.sha }}` (immutable) and `:latest`. `permissions.packages: write` set at the job level. |

All commands work locally without GitHub-specific env vars — `EXCHANGE_RATE_API_*`
come from `.env` locally and from GitHub Secrets in CI. `docker-compose.yml` declares
both as `environment:` so the runner-level env flows into the container (without this,
compose only reads `.env` and `env_file:`, which CI doesn't create).

[WHY] **Pipeline runs against committed fixture data inside Docker in CI**: this is
the only reliable way to detect regressions in the data-quality decisions (e.g. "did
we accidentally start keeping the negative-amount row?").

[WHY] **`publish-image` to GHCR, not a real deploy**: challenge Part 8 requires only
build, test, run pipeline, validate API starts. Publishing the image is the minimal
credible CD increment — proves the artifact is portable, costs nothing, no extra
secrets needed (`GITHUB_TOKEN` is auto-provisioned). A reviewer can `docker pull` and
run the same image CI tested.

[WHY] **Test job validates that JSON specs parse and reference real columns**: a
misnamed column in a spec is otherwise silent until pipeline runtime. Loading specs
in unit tests shifts that error left to PR time.

---

## <observability_spec>

Two correlated streams: structured JSON logs (per-event) and the `data_quality_runs` /
`error_events` tables (per-checkpoint and per-quarantined-row). Both correlate via
`run_id`.

### Structured log schema (stdout, one JSON object per line)

| Field | Type | Required | Notes |
|---|---|---|---|
| `level` | string | yes | `INFO` / `WARNING` / `ERROR` |
| `timestamp` | string | yes | ISO-8601 UTC, millisecond precision |
| `stage` | string | yes | one of: `ingest_customers`, `ingest_orders`, `ingest_events`, `enrich_exchange_rates`, `load_warehouse`, `pipeline`, `api` |
| `message` | string | yes | human-readable summary |
| `run_id` | string | yes (pipeline) | UUID for the pipeline run; correlates with `data_quality_runs.run_id` and `error_events.run_id` |
| `record_id` | string | optional | included for any per-row WARNING (e.g. `"O1003"`) |
| `records_loaded` | int | optional | included on stage-completion INFO |
| `records_skipped` | int | optional | included on stage-completion INFO |
| `validation_id` | string | optional | rule-set run identifier |
| `checkpoint` | string | optional | rule-set name |
| `expectations_evaluated` | int | optional | included on rule-set runs |
| `expectations_succeeded` | int | optional | included on rule-set runs |
| `duration_ms` | int | optional | included on stage-completion INFO |

`httpx`, `httpcore`, and `urllib3` loggers are pinned to `WARNING` so request URLs
(which contain the API key in path) never reach stdout.

### Example log lines per pipeline stage

```json
{"level":"INFO","timestamp":"2026-05-01T05:34:54.554Z","stage":"ingest_customers","message":"Stage complete","run_id":"0b585dfc44f1","records_loaded":6,"duplicates_dropped":1,"duration_ms":128}
{"level":"INFO","timestamp":"2026-05-01T05:34:54.703Z","stage":"ingest_customers","message":"Checkpoint passed","run_id":"0b585dfc44f1","checkpoint":"customers_checkpoint","validation_id":"629dec14c792","expectations_evaluated":7,"expectations_succeeded":7,"duration_ms":19}

{"level":"WARNING","timestamp":"2026-05-01T05:34:54.796Z","stage":"ingest_orders","message":"Pre-filter dropped row: customer_id is null","run_id":"0b585dfc44f1","record_id":"O1003"}
{"level":"WARNING","timestamp":"2026-05-01T05:34:54.797Z","stage":"ingest_orders","message":"Pre-filter dropped row: orphaned customer_id","run_id":"0b585dfc44f1","record_id":"O1005"}
{"level":"WARNING","timestamp":"2026-05-01T05:34:54.798Z","stage":"ingest_orders","message":"Pre-filter dropped row: negative or invalid amount","run_id":"0b585dfc44f1","record_id":"O1004"}
{"level":"INFO","timestamp":"2026-05-01T05:34:54.992Z","stage":"ingest_orders","message":"Stage complete","run_id":"0b585dfc44f1","records_loaded":2,"records_skipped":3,"duration_ms":288}

{"level":"INFO","timestamp":"2026-05-01T05:34:56.416Z","stage":"enrich_exchange_rates","message":"Fetched rates","run_id":"0b585dfc44f1","duration_ms":1210,"currencies":["BRL","USD"]}
{"level":"INFO","timestamp":"2026-05-01T05:34:56.553Z","stage":"load_warehouse","message":"Stage complete","run_id":"0b585dfc44f1","records_loaded":2,"duration_ms":135}
{"level":"INFO","timestamp":"2026-05-01T05:34:56.557Z","stage":"pipeline","message":"Pipeline complete","run_id":"0b585dfc44f1"}
```

[WHY] **`run_id` on every log line and every DB row**: one identifier ties together
log search, the `/data-quality` endpoint, and the `/error-events` endpoint for any
pipeline run.

[WHY] **Logs to stdout, not files**: Docker captures stdout natively, CI tails it,
log-aggregation tooling (Loki, Cloud Logging) ingests stdout by default. A log file
would force a volume mount.
