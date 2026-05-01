# Prompts & Decision Log

Chronological log of LLM prompts used during the project and the technical decisions that
came out of them. Per `CLAUDE.md`, every non-obvious decision is recorded here.

---

## 2026-04-30 — Architecture design

**Prompt:** `docs/data_architecture_design_prompt.md`
**Output:** `docs/data_architecture.md`

### Key decisions and why

- **SQLite, single file** — required by the prompt; no external server, Docker-friendly,
  sufficient for the data volumes.
- **One Docker image for pipeline + API** — they share dependencies; two images would
  duplicate the dependency tree without isolating any meaningful boundary.
- **Staging table `staging_orders`** between `ingest_orders` and `load_warehouse` — orders
  ingestion and exchange-rate enrichment are separate stages and must each be independently
  re-runnable. A staging table makes the hand-off durable and inspectable.
- **Discard rather than impute** for: null `customer_id` in orders, orphaned `customer_id=99`
  in orders/events, negative `amount`, invalid timestamp. Each of these would require
  inventing semantics not present in the source. Discards are logged at WARN with
  `record_id` so the audit trail survives without polluting the warehouse.
- **Keep with NULL** for: missing `name` and missing `country` in customers. Email is a
  recoverable identifier and orders for these customers remain valid. NULLs are excluded
  from country aggregations explicitly via `WHERE country IS NOT NULL`.
- **Denormalize `exchange_rate` and `amount_usd` into `orders`** rather than computing at
  query time. Captures the rate that was used at load time — auditability without
  reproducing the lookup, and analysts don't have to join `exchange_rates`.
- **Enrichment aborts on persistent API failure** rather than silently skipping affected
  orders. Silent drops would corrupt revenue totals without an obvious signal.
- **Logs go to stdout as JSON lines** — Docker captures stdout natively; a log file would
  force a volume mount.
- **Single `/metrics` endpoint** delivering all three aggregates — matches the spec, lets
  analysts pull dashboard data in one call. Splitting later is trivial; merging later
  would be a breaking change.
- **Make targets mirror CI jobs 1:1** — the challenge explicitly requires local
  reproducibility. Any drift between `make` and CI breaks that contract.

---

## 2026-04-30 — Architecture design revised: Great Expectations as DQ framework

**Prompt:** `docs/data_architecture_design_prompt.md` (re-run with framework constraint)
**Output:** `docs/data_architecture.md` (rewritten)

This revision supersedes the prior version. Reasons for adopting GX and the resulting
design choices:

- **GX 1.x with `FileDataContext`** — suites and checkpoints version-controlled in git
  as JSON/YAML so the data contract evolves alongside code. Cloud adds an external
  dependency the challenge does not require; Ephemeral loses the git-tracked contract.
- **Pandas datasource (not SQLite-native)** — the natural validation point is the
  in-memory DataFrame *before* the warehouse write. SQLite-native validation would
  mean bad rows reach the warehouse before being caught.
- **Pre-filter + GX gate pattern** — every "discard" decision is a pre-filter in code;
  the post-clean checkpoint asserts the issue has been removed. The expectation is the
  contract; the filter is the implementation. If they drift, the gate catches it.
- **Validate cleaned DataFrames, not raw input** — the suite expresses the post-clean
  contract. Validating raw input would always fail and require a parallel "raw" suite;
  the cleaner pattern is "the filter removed the bad rows; now prove it."
- **No checkpoint on `load_warehouse`** — data was already validated in `ingest_orders`
  and only joined here; SQLite FK constraints catch any drift. A second checkpoint would
  duplicate effort without catching new failure modes.
- **`data_quality_runs` summary table** added — GX stores full ValidationResults as JSON
  in `gx/uncommitted/validations/`. The summary table is a flat, queryable index for
  the API endpoint, avoiding parsing GX JSON at request time.
- **New `GET /data-quality` endpoint** — the whole point of adopting GX is making data
  quality a first-class artifact; an endpoint exposing the contract turns it into
  something downstream consumers can monitor or alert on, not just a CI artifact.
- **CI publishes Data Docs as an artifact** — the human-readable HTML report is GX's
  killer feature; publishing it lets non-engineering stakeholders audit data-quality
  decisions without reading code.
- **Test asserts every suite parses + references real columns** — a misnamed column in
  an expectation file is otherwise silent until pipeline runtime. Loading suites in
  unit tests shifts that error left to PR time.
- **`run_id` correlates logs ↔ `data_quality_runs` ↔ GX validation store** — one
  identifier ties together log search, the API endpoint, and the Data Docs HTML.

---

## 2026-04-30 — Implementation

Filled in all stubbed modules. Notes:

- **Python version constraint:** Great Expectations 1.x requires `>=3.10,<3.14`. Local
  Python here is 3.14, so `pip install -e ".[dev]"` fails on the GX dep. Two options
  for local work: (a) install Python 3.11–3.13, or (b) run everything via Docker
  (the image targets 3.11). CI uses 3.11.
- **Pre-filter strategy in `ingest_orders`/`ingest_events`** — implemented as explicit
  Python predicates that mirror each gating expectation in the suite. Drift between
  filter and expectation is caught by the post-clean checkpoint failing.
- **`event_type` normalization:** lowercase + strip underscores (`LOG_IN` → `login`).
  Canonical set in `events_suite.json` is `{login, purchase, logout, signup}`.
- **Date parsing in `ingest_orders`:** tries `%Y-%m-%d` then `%d-%m-%Y`; unparseable
  values are dropped with a WARN.
- **Exchange rate inversion:** the public `exchangerate.host` API returns
  `rates[CUR]` = how many CUR per 1 USD. Our schema stores `rate_to_usd` as USD per 1
  unit of CUR, so the client inverts: `rate_to_usd = 1 / rates[CUR]`.
- **API dependency override** in `tests/integration/test_api.py` swaps `get_db` to
  return the test connection — avoids opening a fresh SQLite handle per request and
  keeps the seeded fixture visible to the TestClient.
- **What's verified locally:** `tests/unit/test_expectation_suites.py` passes (5/5);
  every expectation in the suite JSON references a column that exists in
  `sql/schema.sql`. Syntax check (`compileall`) clean across `src/` and `tests/`.
- **What's NOT yet verified locally:** the GX runner (`src/common/data_quality.py`)
  and the end-to-end integration tests — neither Docker nor a 3.11–3.13 Python is
  available in this shell. Run `make build && make pipeline` (or any 3.11–3.13 venv
  with `pip install -e ".[dev]"` then `pytest`) to exercise them.

---

## 2026-04-30 — Added docker-compose.yml

**Why:** Two services (`pipeline` one-shot, `api` long-running) share the same image
but differ in command, ports, and which volumes they need. Compose declares that
contract once, lets `docker compose up -d --wait api` block on the healthcheck (no
brittle `sleep 3`), and makes the Makefile targets one-liners.

**How to apply:**
- Local: `docker compose run --rm pipeline` then `docker compose up -d api`.
- Makefile delegates to compose; CI calls Make, so the chain stays single-sourced.
- `env_file` references `.env` with `required: false` so the container falls back to
  defaults in `src/common/config.py` when no `.env` is present.

## 2026-05-01 — Forward EXCHANGE_RATE_API_* into containers via `environment:`

**Why:** CI sets `EXCHANGE_RATE_API_KEY` at the workflow level (runner env), but
Docker Compose does not auto-inherit runner env into the container — only `env_file`
and `environment:` are read. CI never creates a `.env`, so the container started with
an empty key and `fetch_rates_to_usd` raised `EXCHANGE_RATE_API_KEY is not set`
immediately (same-millisecond failure, observed in run `d1fd53b0dd30`). `tenacity`
did not retry because `ExchangeRateError` is not in `retry_if_exception_type`, but
its frames still appeared in the traceback, which is what made the failure look like
a network issue.

**How to apply:** Both services in `docker-compose.yml` now declare
`environment: EXCHANGE_RATE_API_KEY: ${EXCHANGE_RATE_API_KEY:-}` and the URL with a
default. `environment:` overrides `env_file:`, so locally the `.env` value still wins
(the interpolation default is empty); in CI, the workflow-level secret flows runner →
compose interpolation → container.
