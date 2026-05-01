# Ecommerce Data Pipeline

Containerized ecommerce data pipeline that:

1. Ingests local CSV / JSON / JSONL files (`raw_data/`)
2. Cleans, deduplicates, normalizes, and quarantines bad rows into an `error_events` table
3. Enriches orders with live USD exchange rates from the [exchangerate-api.com](https://www.exchangerate-api.com/) API
4. Loads a SQLite warehouse (`data/warehouse.sqlite`)
5. Validates each pipeline stage against declarative JSON rule-sets in `validations/`
6. Serves the data and run results through a FastAPI app

Reference docs:
- **Architecture:** [`docs/data_architecture.md`](docs/data_architecture.md)
- **Decision log:** [`prompts.md`](prompts.md)
- **Original challenge:** [`technical_challenge.md`](technical_challenge.md)

---

## Prerequisites

- **Docker** (24+) with the `docker compose` plugin
- **Make** (optional but recommended) — Windows users: `winget install ezwinports.make`
- **An exchangerate-api.com API key** (free tier works) — sign up at
  https://www.exchangerate-api.com/ and copy the key

For purely local runs (no Docker) you also need:
- **Python 3.11+** (3.11–3.14 supported)

---

## Quick start (Docker — recommended)

```bash
# 1. Configure the exchange-rate API key
cp .env.example .env
# edit .env and set EXCHANGE_RATE_API_KEY=<your-key>

# 2. Build the image, run the pipeline, start the API
make build
make pipeline
make api

# 3. Hit the API
curl http://localhost:8000/healthz
curl http://localhost:8000/customers?limit=3
curl http://localhost:8000/metrics

# 4. When done
make api-stop
```

The pipeline will:
- Load `raw_data/customers.csv`, `orders.json`, `events.jsonl`
- Apply per-stage rule-sets, quarantining bad rows into `error_events`
- Fetch live USD exchange rates for the currencies that appear in clean orders
- Write the final warehouse to `data/warehouse.sqlite`
- Print structured JSON logs per stage to stdout

Re-running the pipeline is **idempotent** — it always produces the same warehouse from the same inputs.

---

## All Make targets

Every target delegates to `docker compose`, so the same commands run identically locally and in CI.

| Target | What it does |
|---|---|
| `make install` | `pip install -e ".[dev]"` — only needed for the local-Python flow |
| `make lint` | `ruff check . && ruff format --check .` |
| `make test` | `pytest tests/` |
| `make build` | `docker compose build` |
| `make pipeline` | `docker compose run --rm pipeline` — one-shot pipeline run |
| `make api` | `docker compose up -d --wait api` — starts the API at `http://localhost:8000` |
| `make api-stop` | `docker compose down` |
| `make api-smoke` | Boots the API, hits `/healthz`, `/data-quality`, `/customers?limit=1`, then tears down |
| `make clean` | Deletes `data/*.sqlite` and `__pycache__` |

### Direct `docker compose` equivalents (no Make)

```bash
docker compose build
docker compose run --rm pipeline
docker compose up -d --wait api
curl http://localhost:8000/healthz
docker compose down
```

---

## Run locally without Docker

Useful for fast iteration on tests or for IDE debugging.

```bash
# 1. Create a venv (any Python ≥ 3.11)
python -m venv .venv
source .venv/bin/activate           # macOS / Linux
.venv\Scripts\activate              # Windows PowerShell

# 2. Install
pip install -e ".[dev]"

# 3. Provide env vars
cp .env.example .env
# set EXCHANGE_RATE_API_KEY in .env

# 4. Run
pytest                              # 12 tests, ~3s
python -m src.pipeline.run          # writes data/warehouse.sqlite
uvicorn src.api.main:app --reload   # API at http://localhost:8000
```

---

## Pipeline stages

The orchestrator (`src/pipeline/run.py`) runs five stages in order. Any failure aborts
the run with a non-zero exit. Each stage emits structured JSON logs to stdout and writes
a row to the `data_quality_runs` table.

| # | Stage | Reads | Writes |
|---|---|---|---|
| 1 | `ingest_customers` | `raw_data/customers.csv` | `customers`, `error_events` (duplicates) |
| 2 | `ingest_orders` | `raw_data/orders.json` | `staging_orders`, `error_events` (null/orphan/negative/bad-date) |
| 3 | `ingest_events` | `raw_data/events.jsonl` | `events`, `error_events` (orphan/bad-timestamp/parse) |
| 4 | `enrich_exchange_rates` | API + `staging_orders` | `exchange_rates` |
| 5 | `load_warehouse` | `staging_orders ⨝ exchange_rates` | `orders` (with `amount_usd`); truncates staging |

### What gets quarantined

Bad rows are not silently dropped. They land in `error_events` with a stable
`reason` code, the `source_record_id`, and the original payload as JSON. Examples
from the supplied fixture data:

| Row | Stage | Reason |
|---|---|---|
| customers.csv duplicate (cid=3) | `ingest_customers` | `customer_id_duplicate` |
| orders.json `O1003` | `ingest_orders` | `customer_id_null` |
| orders.json `O1004` (-50.00) | `ingest_orders` | `amount_negative_or_invalid` |
| orders.json `O1005` (cid=99) | `ingest_orders` | `customer_id_orphan` |
| events.jsonl `E4` (cid=99) | `ingest_events` | `customer_id_orphan` |
| events.jsonl `E6` (`invalid_timestamp`) | `ingest_events` | `timestamp_invalid` |

Drill in via `GET /error-events`.

---

## API access

After `make api`, the API is at `http://localhost:8000`.
Interactive Swagger UI: `http://localhost:8000/docs`.

| Endpoint | Description |
|---|---|
| `GET /healthz` | Liveness probe |
| `GET /customers` | Paginated customer list. Optional `?country=BR` |
| `GET /orders` | Paginated orders. Optional `?customer_id=`, `?status=`, `?currency=` |
| `GET /metrics` | Revenue per customer, country stats, login→purchase funnel |
| `GET /data-quality` | Latest run's per-stage rule-set summary + quarantine counts |
| `GET /error-events` | Paginated quarantined rows. Optional `?run_id=`, `?stage=`, `?reason=` |

All list endpoints accept `?limit=` (default 100, max 500) and `?offset=` (default 0).

### Example responses

```bash
$ curl -s http://localhost:8000/customers?limit=2 | jq
{
  "items": [
    {"customer_id":1,"name":"Ana Silva","email":"ana@email.com","country":"BR","created_at":"2022-01-10"},
    {"customer_id":2,"name":"John Doe","email":"john@email.com","country":"US","created_at":"2021-11-03"}
  ],
  "total": 6, "limit": 2, "offset": 0
}

$ curl -s http://localhost:8000/orders | jq
{
  "items": [
    {"order_id":"O1001","customer_id":1,"amount_original":250.5,"currency_original":"BRL",
     "exchange_rate":0.2003,"amount_usd":50.19,"status":"completed","order_date":"2023-07-10"},
    {"order_id":"O1002","customer_id":2,"amount_original":99.9,"currency_original":"USD",
     "exchange_rate":1.0,"amount_usd":99.9,"status":"cancelled","order_date":"2023-07-11"}
  ],
  "total": 2, "limit": 100, "offset": 0
}

$ curl -s http://localhost:8000/metrics | jq
{
  "revenue_per_customer": [{"customer_id":1,"revenue_usd":50.19}],
  "country_stats": [
    {"country":"BR","order_count":1,"avg_amount_usd":50.19},
    {"country":"US","order_count":1,"avg_amount_usd":99.9}
  ],
  "event_funnel": [
    {"customer_id":1,"logins":1,"purchases":1},
    {"customer_id":2,"logins":1,"purchases":0}
  ]
}

$ curl -s http://localhost:8000/data-quality | jq
{
  "run_id": "0b585dfc44f1",
  "overall_success": true,
  "stages": [
    {"stage":"ingest_customers","checkpoint":"customers_checkpoint",
     "success":true,"evaluated":7,"succeeded":7,"started_at":"...","duration_ms":19},
    ...
  ],
  "error_events_summary": [
    {"stage":"ingest_orders","reason":"amount_negative_or_invalid","count":1},
    {"stage":"ingest_orders","reason":"customer_id_null","count":1},
    {"stage":"ingest_orders","reason":"customer_id_orphan","count":1},
    {"stage":"ingest_events","reason":"customer_id_orphan","count":1},
    {"stage":"ingest_events","reason":"timestamp_invalid","count":1}
  ]
}
```

---

## Configuration (`.env`)

Copied from `.env.example`:

| Variable | Default | Notes |
|---|---|---|
| `EXCHANGE_RATE_API_URL` | `https://v6.exchangerate-api.com/v6` | Base URL; the client appends `/{key}/latest/USD` |
| `EXCHANGE_RATE_API_KEY` | *(empty — required)* | exchangerate-api.com key |
| `WAREHOUSE_PATH` | `data/warehouse.sqlite` | Where the SQLite warehouse is written |
| `RAW_DATA_DIR` | `raw_data` | Source files directory |
| `VALIDATIONS_DIR` | `validations` | JSON validation specs directory |
| `LOG_LEVEL` | `INFO` | Standard Python logging level |

In CI the values come from the workflow-level `env:` block + `EXCHANGE_RATE_API_KEY` from
GitHub Secrets. Locally they come from `.env`.

---

## Technical decisions (high level)

Full rationale is in [`prompts.md`](prompts.md) (chronological decision log) and
[`docs/data_architecture.md`](docs/data_architecture.md). The headline decisions:

### Storage and modeling

- **SQLite, single file.** No external server, Docker-friendly, sufficient for the data
  volumes. The whole warehouse is one file under `data/`.
- **Denormalized USD into `orders`.** `exchange_rate` and `amount_usd` are stored on the
  order row, captured at load time. Analysts get USD totals without joining
  `exchange_rates`, and historical orders keep the rate that was actually used (auditable).
- **`staging_orders` between ingestion and load.** Orders ingestion and exchange-rate
  enrichment are separate stages; a staging table makes the hand-off durable and lets
  each stage be re-run independently.

### Data quality

- **Declarative JSON specs in `validations/`** with a small pandas-based runner in
  `src/common/data_quality.py`. Six rule types cover everything we need: `column_exists`,
  `not_null`, `unique`, `between`, `in_set`, `matches_strftime`, `matches_regex`.
  *Earlier revisions used Great Expectations 1.x — removed because the runtime cost of
  debugging GX serialization issues exceeded the benefit for our small ruleset (full
  story in `prompts.md`).*
- **Quarantine, not reject.** Rows that fail pre-filters go into `error_events` with a
  stable `reason` code and the original payload — visible via `/data-quality` and
  `/error-events`. The warehouse contract (only clean rows) is unchanged.
- **First-failing-reason wins per row** so a single defective row doesn't inflate
  multiple reason counts. Pre-filter check order = de-facto reason priority.
- **Post-clean rule-set still aborts the pipeline on failure.** With quarantine in
  place, a rule-set fail signals drift between the pre-filter and the spec —
  fail-fast on a real bug, not on data.

### Exchange-rate enrichment

- **`exchangerate-api.com`** with the API key in the URL path. Falls back to
  `EXCHANGE_RATE_API_URL` env if the user wants a different base.
- **`tenacity` retry** (3× exponential backoff) on transport / timeout / 5xx errors.
  Persistent failure aborts the pipeline rather than silently dropping orders for
  the affected currency.
- **Rates stored as `rate_to_usd`** (USD per 1 unit of currency). The provider returns
  the inverse (`conversion_rates[CUR]` = how many CUR per 1 USD); the client inverts.
- **httpx / httpcore / urllib3 loggers pinned to WARNING** so the request URL (which
  contains the API key) never reaches stdout.

### Observability

- **Structured JSON logs to stdout**, one object per line. Docker captures stdout
  natively; any log-aggregation tool ingests it.
- **`run_id` correlates everything.** Same UUID on every log line, every
  `data_quality_runs` row, every `error_events` row for a given pipeline run.
- **Two endpoints for DQ visibility.** `/data-quality` is a one-shot summary;
  `/error-events` is paginated drill-in. Different access patterns, different endpoints.

### Containerization

- **Single image** for pipeline + API. They share dependencies; two images would
  duplicate the dep tree without isolating any meaningful boundary.
- **`Dockerfile` `CMD` runs the pipeline once, then exec's `uvicorn`.** This makes the
  image deployable to ephemeral hosts (Render free tier) where the warehouse needs to
  be (re)built on every cold start.
- **`docker-compose.yml` declares two services:** `pipeline` (one-shot) and `api`
  (long-running with healthcheck). `environment:` block forwards
  `EXCHANGE_RATE_API_*` so the runner-level env in CI reaches the container.

### CI/CD

- **GitHub Actions: 6 jobs** — `lint` → `test` → `build` → `pipeline` → `api-smoke` →
  `publish-image`. Every command is callable locally via `make`, so there is no
  drift between local dev and CI.
- **`publish-image` to GHCR** on `master` only, gated on the upstream jobs. Tags
  `:${{ github.sha }}` (immutable) and `:latest`. Uses `GITHUB_TOKEN` — no extra
  secrets needed. A reviewer can `docker pull ghcr.io/<repo>:latest` and run the
  same image CI just tested.

### Code style

- **`ruff check` + `ruff format`** for linting and formatting (configured in
  `pyproject.toml`). Enforces `B`, `UP`, `SIM`, `I` plus the defaults.
- **FastAPI dependencies use the modern `Annotated[...]` pattern**:
  `DbConn = Annotated[sqlite3.Connection, Depends(get_db)]`, then
  `def handler(conn: DbConn, ...)`. Idiomatic in current FastAPI and avoids `B008`.

---

## Testing

```bash
make test
```

Runs 12 tests (~3 s):

| Suite | Coverage |
|---|---|
| `tests/unit/test_expectation_suites.py` | Asserts every JSON validation spec parses and references columns that actually exist in `sql/schema.sql` (catches misnamed columns at PR time, not pipeline runtime) |
| `tests/integration/test_pipeline_end_to_end.py` | Runs the full pipeline against `raw_data/` fixtures with a fake exchange-rate client; asserts row counts, quarantine routing, and the warehouse contract |
| `tests/integration/test_api.py` | Boots the FastAPI app via `TestClient` against a seeded warehouse; covers all six endpoints |

---

## Project layout

See [`docs/data_architecture.md`](docs/data_architecture.md) `<project_structure>` for the
full tree. The high-level picture:

```
ecommerce_data_pipeline/
├── raw_data/                  # source CSV / JSON / JSONL
├── data/                      # generated SQLite warehouse (gitignored)
├── sql/schema.sql             # canonical DDL
├── validations/*.json         # declarative DQ specs, one per dataset
├── src/
│   ├── common/                # config, logging, db, exchange_rate_client, data_quality
│   ├── pipeline/              # 5 stages + orchestrator (run.py)
│   └── api/                   # FastAPI app + 5 routers
├── tests/                     # unit + integration
├── docs/                      # architecture + design prompt
├── Dockerfile, docker-compose.yml, Makefile
└── pyproject.toml, .env.example
```
