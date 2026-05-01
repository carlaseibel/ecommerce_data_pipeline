# Data Architecture — Ecommerce Pipeline (Great Expectations edition)

This document is the response to `docs/data_architecture_design_prompt.md`. Every section
maps 1:1 to the prompt's `<output_format>` schema. Non-obvious decisions are tagged `[WHY]`.

**Data quality framework: [Great Expectations](https://greatexpectations.io/) 1.x.**
All row-level validation is expressed as Expectation Suites; pipeline stages execute
Checkpoints as gates between transformation and persistence. Validation results are
stored in the GX `ValidationResultStore` and surfaced both in structured logs and as
HTML Data Docs published from CI.

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
├── gx/                                      # Great Expectations project root
│   ├── great_expectations.yml               # FileDataContext config (pandas datasource)
│   ├── expectations/
│   │   ├── customers_suite.json             # column existence, PK uniqueness, types
│   │   ├── orders_raw_suite.json            # pre-clean: structural expectations
│   │   ├── orders_clean_suite.json          # post-clean: gate for warehouse load
│   │   ├── events_suite.json                # event_type in canonical set, ISO timestamp
│   │   └── exchange_rates_suite.json        # rate > 0, currency ISO-4217
│   ├── checkpoints/
│   │   ├── customers_checkpoint.yml
│   │   ├── orders_clean_checkpoint.yml
│   │   ├── events_checkpoint.yml
│   │   └── exchange_rates_checkpoint.yml
│   └── uncommitted/                         # gitignored
│       ├── validations/                     # ValidationResult JSON store
│       └── data_docs/local_site/            # generated HTML; published in CI
├── src/
│   ├── common/
│   │   ├── config.py                        # paths, base currency, API URL/keys via env
│   │   ├── logging.py                       # structured JSON logger factory
│   │   ├── db.py                            # SQLite connect + bootstrap from schema.sql
│   │   ├── data_quality.py                  # thin wrapper: build_context, run_checkpoint, log result
│   │   └── exchange_rate_client.py          # HTTP client with retry + timeout
│   ├── pipeline/
│   │   ├── ingest_customers.py              # stage 1
│   │   ├── ingest_orders.py                 # stage 2 (writes to staging_orders)
│   │   ├── ingest_events.py                 # stage 3
│   │   ├── enrich_exchange_rates.py         # stage 4
│   │   ├── load_warehouse.py                # stage 5 (staging → final orders)
│   │   └── run.py                           # orchestrator: runs all 5 stages in order
│   └── api/
│       ├── main.py                          # FastAPI app factory
│       ├── deps.py                          # DB connection dependency
│       ├── schemas.py                       # Pydantic response models
│       └── routers/
│           ├── customers.py                 # GET /customers
│           ├── orders.py                    # GET /orders
│           ├── metrics.py                   # GET /metrics
│           └── data_quality.py              # GET /data-quality (latest GX run summary)
├── tests/
│   ├── conftest.py                          # fixtures: tmp sqlite, fake exchange API, ephemeral GX context
│   ├── unit/
│   │   ├── test_ingest_customers.py
│   │   ├── test_ingest_orders.py
│   │   ├── test_ingest_events.py
│   │   ├── test_exchange_rate_client.py
│   │   ├── test_load_warehouse.py
│   │   └── test_expectation_suites.py       # asserts each suite parses + has expected columns
│   └── integration/
│       ├── test_pipeline_end_to_end.py      # runs full pipeline + asserts checkpoint passed
│       └── test_api.py                      # FastAPI TestClient against seeded DB
├── .github/workflows/
│   └── ci.yml                               # lint → test → build → pipeline → api smoke → publish data docs
├── Dockerfile                               # single image runs both pipeline & API
├── docker-compose.yml                       # `pipeline` (one-shot) and `api` (long-running) services on the same image
├── Makefile                                 # local entrypoints (delegate to `docker compose`); satisfies challenge's "Makefile or run_pipeline.sh" requirement
├── pyproject.toml                           # deps (great_expectations==1.*) + ruff/pytest config
├── .env.example                             # EXCHANGE_RATE_API_URL, EXCHANGE_RATE_API_KEY
├── .dockerignore
├── .gitignore                               # excludes gx/uncommitted/, data/warehouse.sqlite
├── prompts.md                               # LLM decision log (per CLAUDE.md)
└── README.md                                # run instructions + decision summary
```

[WHY] **GX `FileDataContext` (not Cloud, not Ephemeral):** suites and checkpoints are
versioned in git as JSON/YAML so the data contract evolves as code. Cloud adds an external
dependency the challenge does not require; Ephemeral loses the git-tracked contract.

[WHY] **Pandas datasource (not SQLite-native):** ingestion happens before the SQLite write,
so the natural validation point is the in-memory DataFrame. Validating after the SQLite
write would mean bad rows reach the warehouse before being caught.

[WHY] **`gx/uncommitted/` gitignored:** GX writes validation results and Data Docs HTML
into this directory by convention. Outputs change every run and shouldn't pollute git.

---

## <data_quality_decisions>

Every issue is encoded as an Expectation. The **Decision** column states the runtime
behavior; the **Expectation(s)** column names the GX expectation that enforces it.

| Issue | Source | Decision | Justification | Expectation(s) |
|---|---|---|---|---|
| Duplicate row for `customer_id=3` | customers.csv | **Pre-filter:** drop duplicate `customer_id`s, keep first; **gate:** suite asserts uniqueness post-filter | Rows are byte-identical; PK uniqueness must hold. Logged with `duplicates_dropped` count. | `expect_column_values_to_be_unique("customer_id")` |
| Missing `name` (`customer_id=5`) | customers.csv | **Keep**, store NULL | Email is the recoverable identifier; dropping breaks order joins for that customer. | `expect_column_values_to_not_be_null("email")` *(name not asserted non-null)* |
| Missing `country` (`customer_id=6`) | customers.csv | **Keep**, store NULL | Country only affects per-country metrics; orders for this customer remain valid. | *(country has no non-null expectation; format checked when present via regex)* |
| `customer_id` is `null` (`O1003`) | orders.json | **Pre-filter:** drop; **gate:** suite asserts not-null | Every analytical query is per-customer; an unattributed order pollutes joins. | `expect_column_values_to_not_be_null("customer_id")` |
| Orphaned `customer_id=99` (`O1005`, `E4`) | orders.json, events.jsonl | **Pre-filter:** drop rows whose `customer_id` is not in `customers`; **gate:** referential integrity expectation | Referential integrity: no joinable customer; aggregations are undefined. | `expect_column_values_to_be_in_set("customer_id", value_set=<loaded customer_ids>)` |
| Negative `amount=-50.00` (`O1004`) | orders.json | **Pre-filter:** drop; **gate:** non-negative expectation | The schema has no refund/credit type; treating negatives as revenue is wrong, treating them as refunds invents semantics. | `expect_column_values_to_be_between("amount_original", min_value=0)` |
| Mixed-case `status` | orders.json | **Normalize** to lowercase on ingest; **gate:** value set | `GROUP BY status` requires consistent casing; lowercase is the least-surprise convention. | `expect_column_values_to_be_in_set("status", ["completed","cancelled"])` |
| Two date formats (YYYY-MM-DD, DD-MM-YYYY) | orders.json | **Parse both**, store ISO; unparseable rows discarded | Single canonical format enables lexicographic ordering and SQLite date functions. | `expect_column_values_to_match_strftime_format("order_date", "%Y-%m-%d")` |
| Mixed currencies (BRL/USD/EUR) | orders.json | **Preserve original** + add `amount_usd` and `exchange_rate` columns | Auditability: enrichment must be reversible. | `expect_column_values_to_match_regex("currency_original", "^[A-Z]{3}$")` |
| Mixed `event_type` casing (`login`/`LOG_IN`) | events.jsonl | **Normalize:** lowercase + strip underscores → both → `login` | Funnel analysis requires a single canonical token. | `expect_column_values_to_be_in_set("event_type", ["login","purchase",...])` |
| Invalid timestamp `"invalid_timestamp"` (`E6`) | events.jsonl | **Pre-filter:** drop unparseable; **gate:** strftime expectation | An event with no time has no place in a funnel; imputation would fabricate. | `expect_column_values_to_match_strftime_format("event_timestamp", "%Y-%m-%dT%H:%M:%SZ")` |
| Exchange rate fetched but `<= 0` or non-numeric | API response | **Abort enrichment** stage with ERROR | A non-positive rate would corrupt every USD conversion. | `expect_column_values_to_be_between("rate_to_usd", min_value=0, strict_min=True)` |

**Pattern:** every "discard" decision is implemented as a **pre-filter** in code, then the
**post-clean checkpoint** asserts the issue has been removed. If the checkpoint fails, the
stage aborts — meaning the filter and the expectation are out of sync, which is a code bug
rather than a data issue.

[WHY] **Pre-filter + gate (not pre-filter alone):** the expectation is the contract; the
filter is the implementation. Running the gate after filtering catches drift if the filter
is changed without updating the expectation, and vice versa.

[WHY] **No quarantine table:** the challenge does not require one and input volumes are
trivial. Discarded rows are visible in (a) GX validation results showing the original
violation count and (b) WARN logs with `record_id`. If quarantine becomes necessary, GX
`unexpected_index_list` already gives us the row IDs to write into a separate table.

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
    currency      TEXT PRIMARY KEY,             -- ISO-4217, e.g. "BRL"
    rate_to_usd   REAL NOT NULL,                -- 1 unit of `currency` = rate_to_usd USD
    fetched_at    TEXT NOT NULL                 -- ISO-8601 UTC
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
-- Truncated at the start of each pipeline run.
CREATE TABLE IF NOT EXISTS staging_orders (
    order_id          TEXT PRIMARY KEY,
    customer_id       INTEGER NOT NULL,
    amount_original   REAL NOT NULL,
    currency_original TEXT NOT NULL,
    status            TEXT NOT NULL,
    order_date        TEXT NOT NULL
);

-- Validation summary surfaced via GET /data-quality.
-- Written by each pipeline stage after its checkpoint runs.
CREATE TABLE IF NOT EXISTS data_quality_runs (
    run_id          TEXT NOT NULL,              -- pipeline run UUID
    stage           TEXT NOT NULL,              -- e.g. "ingest_orders"
    checkpoint      TEXT NOT NULL,              -- GX checkpoint name
    success         INTEGER NOT NULL,           -- 1 or 0
    evaluated       INTEGER NOT NULL,           -- # expectations evaluated
    succeeded       INTEGER NOT NULL,           -- # expectations succeeded
    started_at      TEXT NOT NULL,              -- ISO-8601 UTC
    duration_ms     INTEGER NOT NULL,
    PRIMARY KEY (run_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_dq_started ON data_quality_runs(started_at DESC);
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

[WHY] **`data_quality_runs` table** (small, summary-only): GX itself stores full
ValidationResults as JSON in `gx/uncommitted/validations/`. The summary table is a
flat, queryable index for the API endpoint, avoiding parsing GX JSON at request time.

[WHY] `exchange_rate` and `amount_usd` denormalized into `orders`: queries are read-mostly
and the rate captured at load time gives auditability without re-running the lookup.

---

## <pipeline_stages>

Each stage follows the same shape: **load → transform → pre-filter → GX checkpoint (gate) →
write**. The checkpoint is the only point at which a stage can fail with a data-quality
error.

| Stage | Input | Output | Key transformations | GX checkpoint | Error behavior |
|---|---|---|---|---|---|
| **ingest_customers** | `raw_data/customers.csv` | `customers` table | Drop duplicate `customer_id`s; coerce types; preserve NULL `name`/`country` | `customers_checkpoint` (suite: `customers_suite`) | Checkpoint fail → ERROR + abort. Idempotent: `INSERT OR REPLACE` on PK. |
| **ingest_orders** | `raw_data/orders.json` | `staging_orders` table | Lowercase `status`; parse both date formats to ISO; pre-filter rows with null/orphaned `customer_id` or negative `amount` | `orders_clean_checkpoint` (suite: `orders_clean_suite`) — runs against the cleaned DataFrame, **not** the raw input | Truncates `staging_orders` first. Per-row pre-filter rejects → WARN with `record_id`. Checkpoint fail → ERROR + abort (means filter and suite are out of sync). |
| **ingest_events** | `raw_data/events.jsonl` | `events` table | Normalize `event_type` (lowercase, strip `_`); parse ISO timestamp; pre-filter unparseable timestamps and orphaned `customer_id` | `events_checkpoint` (suite: `events_suite`) | Per-line JSON failure → WARN + skip. Checkpoint fail → ERROR + abort. Idempotent: `INSERT OR REPLACE` on `event_id`. |
| **enrich_exchange_rates** | distinct `currency_original` from `staging_orders` | `exchange_rates` table | Fetch USD rate per currency; build DataFrame `(currency, rate_to_usd, fetched_at)` | `exchange_rates_checkpoint` (suite: `exchange_rates_suite`) | API timeout → retry up to 3× with exponential backoff. Persistent failure or checkpoint fail → ERROR + abort pipeline. Idempotent: `INSERT OR REPLACE` on `currency`. |
| **load_warehouse** | `staging_orders` ⨝ `exchange_rates` | `orders` table | Inner-join staging to rates; compute `amount_usd`; copy `rate_to_usd` into `exchange_rate` | *(no separate checkpoint — relies on `orders_clean_suite` already passed and FK constraints)* | Missing rate for a staged currency → ERROR + abort. Idempotent: `INSERT OR REPLACE`; staging truncated at end. |

**After each checkpoint runs, the stage:**
1. Writes a row into `data_quality_runs` (run_id, stage, success, counts, duration).
2. Emits a structured log line including the GX `validation_id`.
3. On failure, raises and the orchestrator aborts the pipeline with non-zero exit.

[WHY] **Validation runs against the cleaned DataFrame, not raw input:** the suite expresses
the post-clean contract. Validating raw input would always fail (negative amount, orphaned
IDs, etc.) and require a separate "raw" suite. The cleaner pattern is "the filter removed
the bad rows; now prove it" — a single suite serves as both spec and acceptance test.

[WHY] **No checkpoint on `load_warehouse`:** the data was already validated in
`ingest_orders` and only joined here; SQLite FK constraints catch any drift. A second
checkpoint would duplicate effort without catching new failure modes.

---

## <api_contract>

All endpoints return JSON. Pagination uses `limit` (default 100, max 500) and `offset` (default 0).

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

Example response:
```json
{
  "items": [
    {"customer_id": 1, "name": "Ana Silva", "email": "ana@email.com",
     "country": "BR", "created_at": "2022-01-10"}
  ],
  "total": 1, "limit": 100, "offset": 0
}
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

Example response:
```json
{
  "items": [
    {"order_id": "O1001", "customer_id": 1, "amount_original": 250.50,
     "currency_original": "BRL", "exchange_rate": 0.20, "amount_usd": 50.10,
     "status": "completed", "order_date": "2023-07-10"}
  ],
  "total": 1, "limit": 100, "offset": 0
}
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

Example response:
```json
{
  "revenue_per_customer": [{"customer_id": 1, "revenue_usd": 50.10}],
  "country_stats": [{"country": "BR", "order_count": 1, "avg_amount_usd": 50.10}],
  "event_funnel": [{"customer_id": 1, "logins": 1, "purchases": 1}]
}
```

### `GET /data-quality`

No query params. Returns the latest GX checkpoint run summary per stage. Surfaces the
data-quality posture of the warehouse to API consumers without forcing them to read the
GX Data Docs HTML.

```python
class DataQualityRun(BaseModel):
    stage: str
    checkpoint: str
    success: bool
    evaluated: int
    succeeded: int
    started_at: datetime
    duration_ms: int

class DataQualityResponse(BaseModel):
    run_id: str
    overall_success: bool
    stages: list[DataQualityRun]
    data_docs_url: Optional[str]    # populated in CI to point at published artifact
```

Example response:
```json
{
  "run_id": "9c2d…",
  "overall_success": true,
  "stages": [
    {"stage": "ingest_customers", "checkpoint": "customers_checkpoint",
     "success": true, "evaluated": 5, "succeeded": 5,
     "started_at": "2026-04-30T10:23:01Z", "duration_ms": 84},
    {"stage": "ingest_orders", "checkpoint": "orders_clean_checkpoint",
     "success": true, "evaluated": 8, "succeeded": 8,
     "started_at": "2026-04-30T10:23:01Z", "duration_ms": 122}
  ],
  "data_docs_url": null
}
```

[WHY] **`/data-quality` endpoint added:** the whole point of adopting GX is making data
quality a first-class artifact; an endpoint exposing the contract turns it into something
downstream consumers can monitor or alert on, not just a CI artifact.

---

## <cicd_pipeline>

`.github/workflows/ci.yml` — six jobs, each runs the same command available locally via `make`:

| # | Job | Command | What it produces / validates |
|---|---|---|---|
| 1 | **lint** | `make lint` (`ruff check . && ruff format --check .`) | Validates style. Fails on style violations. |
| 2 | **test** | `make test` (`pytest tests/`) | Runs unit + integration tests, including `test_expectation_suites.py` which asserts every GX suite parses and references real columns. Produces `coverage.xml`. |
| 3 | **build** | `make build` (`docker build -t ecommerce-pipeline .`) | Produces the runtime image. Cached via GHA Docker layer cache. |
| 4 | **pipeline** | `make pipeline` (`docker compose run --rm pipeline`) | Runs the full pipeline against committed fixture data. Asserts every checkpoint succeeded and `SELECT COUNT(*) FROM orders > 0`. Mock exchange-rate URL via env override. |
| 5 | **api-smoke** | `make api-smoke` (`docker compose up -d --wait api`, then curl `/healthz`, `/data-quality`, `/customers?limit=1`) | Validates the API boots (compose healthcheck) and `/data-quality` returns `overall_success: true` against the warehouse from job 4. |
| 6 | **publish-data-docs** | `make data-docs` (`great_expectations docs build`) then upload `gx/uncommitted/data_docs/local_site` as a GH Pages / artifact | Publishes the human-readable validation report. Linked from the PR comment so reviewers can inspect what the suite actually validated. |

All commands work locally without GitHub-specific env vars. `EXCHANGE_RATE_API_URL` and
`EXCHANGE_RATE_API_KEY` come from `.env` locally and from GitHub Secrets in CI; reads via
`src/common/config.py`.

[WHY] **Test job validates that suites parse:** a misnamed column in an expectation file
is silent until the pipeline runs. A test that loads each suite and cross-checks column
names against `sql/schema.sql` shifts that error left to PR time.

[WHY] **Data Docs published as a job, not skipped:** GX's killer feature is the human-readable
HTML report. Publishing it as a CI artifact (or GH Pages site) means non-engineering
stakeholders can audit data-quality decisions without reading code.

[WHY] **`gx/` mounted into the pipeline container:** the GX `FileDataContext` reads suites
and writes validation results from disk. Without the mount, every container run starts
without history and Data Docs cannot be built.

[WHY] **`docker-compose.yml` instead of raw `docker run`:** two services share the same
image but have different commands and volume sets (pipeline mounts `raw_data/`; API
doesn't). Compose declares the contract once; the Makefile becomes one-line targets
(`docker compose run --rm pipeline`, `docker compose up -d api`). The compose
healthcheck on `/healthz` lets `--wait` block until the API is actually ready, which
removes the brittle `sleep 3` from the smoke test.

---

## <observability_spec>

Two correlated streams: structured JSON logs (per-event) and GX ValidationResults (per-checkpoint).

### Structured log schema (stdout, one JSON object per line)

| Field | Type | Required | Notes |
|---|---|---|---|
| `level` | string | yes | `INFO` / `WARN` / `ERROR` |
| `timestamp` | string | yes | ISO-8601 UTC, millisecond precision |
| `stage` | string | yes | `ingest_customers`, `ingest_orders`, `ingest_events`, `enrich_exchange_rates`, `load_warehouse`, `api` |
| `message` | string | yes | human-readable summary |
| `run_id` | string | yes (pipeline) | UUID for the pipeline run; correlates with `data_quality_runs.run_id` |
| `record_id` | string | optional | included for any per-row WARN/ERROR (e.g. `"O1003"`) |
| `records_loaded` | int | optional | included on stage-completion INFO |
| `records_skipped` | int | optional | included on stage-completion INFO |
| `validation_id` | string | optional | GX ValidationResult identifier; included on checkpoint runs |
| `checkpoint` | string | optional | GX checkpoint name |
| `expectations_evaluated` | int | optional | included on checkpoint runs |
| `expectations_succeeded` | int | optional | included on checkpoint runs |
| `duration_ms` | int | optional | included on stage-completion INFO |

### GX ValidationResults

Stored at `gx/uncommitted/validations/<suite>/<run>/<batch>.json` by the GX
`ValidationResultStore`. Includes per-expectation success, observed values, and
`unexpected_index_list` for failing expectations — providing the row-level audit trail.
Rendered as HTML via `great_expectations docs build` (CI job 6).

### Example log lines per pipeline stage

```json
{"level":"INFO","timestamp":"2026-04-30T10:23:01.142Z","stage":"ingest_customers","run_id":"9c2d…","message":"Stage complete","records_loaded":6,"duplicates_dropped":1,"duration_ms":42}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.190Z","stage":"ingest_customers","run_id":"9c2d…","message":"Checkpoint passed","checkpoint":"customers_checkpoint","validation_id":"v-7f1a","expectations_evaluated":5,"expectations_succeeded":5,"duration_ms":84}

{"level":"WARN","timestamp":"2026-04-30T10:23:01.218Z","stage":"ingest_orders","run_id":"9c2d…","message":"Pre-filter dropped row: customer_id is null","record_id":"O1003"}
{"level":"WARN","timestamp":"2026-04-30T10:23:01.219Z","stage":"ingest_orders","run_id":"9c2d…","message":"Pre-filter dropped row: orphaned customer_id=99","record_id":"O1005"}
{"level":"WARN","timestamp":"2026-04-30T10:23:01.220Z","stage":"ingest_orders","run_id":"9c2d…","message":"Pre-filter dropped row: negative amount","record_id":"O1004"}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.225Z","stage":"ingest_orders","run_id":"9c2d…","message":"Stage complete","records_loaded":2,"records_skipped":3,"duration_ms":15}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.347Z","stage":"ingest_orders","run_id":"9c2d…","message":"Checkpoint passed","checkpoint":"orders_clean_checkpoint","validation_id":"v-7f1b","expectations_evaluated":8,"expectations_succeeded":8,"duration_ms":122}

{"level":"WARN","timestamp":"2026-04-30T10:23:01.401Z","stage":"ingest_events","run_id":"9c2d…","message":"Pre-filter dropped row: invalid timestamp","record_id":"E6"}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.405Z","stage":"ingest_events","run_id":"9c2d…","message":"Stage complete","records_loaded":4,"records_skipped":2,"duration_ms":11}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.488Z","stage":"ingest_events","run_id":"9c2d…","message":"Checkpoint passed","checkpoint":"events_checkpoint","validation_id":"v-7f1c","expectations_evaluated":6,"expectations_succeeded":6,"duration_ms":83}

{"level":"INFO","timestamp":"2026-04-30T10:23:01.812Z","stage":"enrich_exchange_rates","run_id":"9c2d…","message":"Fetched rates","currencies":["BRL","USD","EUR"],"duration_ms":495}
{"level":"INFO","timestamp":"2026-04-30T10:23:01.840Z","stage":"enrich_exchange_rates","run_id":"9c2d…","message":"Checkpoint passed","checkpoint":"exchange_rates_checkpoint","validation_id":"v-7f1d","expectations_evaluated":3,"expectations_succeeded":3,"duration_ms":28}

{"level":"INFO","timestamp":"2026-04-30T10:23:01.870Z","stage":"load_warehouse","run_id":"9c2d…","message":"Stage complete","records_loaded":2,"duration_ms":22}
```

[WHY] **`run_id` on every log line:** correlates structured logs with the
`data_quality_runs` table and the GX validation store. One identifier ties together log
search, the API endpoint, and the Data Docs HTML for any pipeline run.

[WHY] **Logs to stdout, not files:** Docker captures stdout natively, CI tails it, and any
log-aggregation tooling (Loki, Cloud Logging) ingests stdout by default. GX validation
JSON is the durable audit artifact; logs are the operational stream.
