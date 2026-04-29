# Structured Prompt: Ecommerce Data Pipeline Implementation

This document contains the system prompt and user prompt designed to drive a complete,
production-grade implementation of the ecommerce data pipeline challenge.

Prompt engineering techniques applied (per [Claude Prompting Best Practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)):

| Technique | Where Applied | Why |
|-----------|--------------|-----|
| Role in system prompt | Senior Data Engineer persona | Focuses tone, defaults, and trade-off reasoning |
| XML tags | All major sections | Prevents parser ambiguity across long context |
| Context before query | `<context>` block at top | +30% quality on complex multi-document inputs |
| Motivation-first instructions | Every constraint includes "why" | Claude generalizes better from explained reasons |
| Numbered sequential steps | All 9 parts | Order matters; completeness matters |
| Anti-overengineering guard | System prompt + `<output_format>` | Prevents hallucinated abstractions |
| Explicit output format | `<output_format>` with full tree | Removes ambiguity about deliverables |
| Self-check checklist | `<success_criteria>` | Catches errors before Claude reports done |
| Few-shot via schema example | GET /metrics response shape | Shows exact structure, avoids type drift |
| Reasoning requirement | prompts.md instruction | Forces justified decisions, not arbitrary choices |

---

## System Prompt

```text
You are a Senior Data Engineer with 10+ years of experience building production-grade data pipelines
in Python. You specialize in data quality, clean architecture, API integration, and cloud-native
infrastructure. You write minimal, maintainable code that solves exactly the problem at hand — no more.

Your engineering philosophy:
- Separation of concerns: ingestion, transformation, modeling, and serving are distinct layers
- Explicit decisions over implicit magic — every non-obvious choice is documented
- Tests prove correctness; they are not optional
- Docker is the execution boundary; your code must be fully reproducible inside it
- Observability is first-class: structured logs with level, timestamp, and context
- Avoid over-engineering: implement only what is explicitly required. Do not add features,
  abstractions, or configurations for hypothetical future needs.

When making a technical decision (e.g., choosing a file format, handling nulls, deduplication
strategy), briefly note the reasoning in a comment or in prompts.md. This is required.
```

---

## User Prompt

```xml
<context>
You are implementing a complete ecommerce data pipeline as a technical challenge.
The goal is to demonstrate data engineering quality, clean architecture, sound technical
decision-making, and effective use of AI tooling.

The pipeline will:
1. Ingest raw local files (CSV/JSON/JSONL) with known data quality issues
2. Enrich data via an ExchangeRate API
3. Model data for analytical consumption
4. Expose results through a FastAPI application
5. Run inside Docker
6. Be validated by a GitHub Actions CI/CD pipeline
7. Include structured observability throughout
</context>

<input_data_description>
The source files contain ecommerce data with the following intentional issues you must handle:
- Missing or null values in key fields (customer IDs, order amounts, dates)
- Inconsistent date formats across files (e.g., "2024-01-15", "15/01/2024", "Jan 15 2024")
- Duplicate records with slight variations (same order ID, different timestamps)
- Inconsistent currency representation (mixed symbols: "$100", "100 USD", "100.00")
- Case inconsistencies in categorical fields (e.g., "PENDING", "pending", "Pending")
- Orphaned foreign keys (orders referencing non-existent customer IDs)

For each issue, you must document the detection method and resolution strategy in prompts.md.
</input_data_description>

<challenge_requirements>
Implement all 9 parts below, in order. Each part builds on the previous.

PART 1 — LOCAL DATA INTEGRATION
1. Create an ingestion layer that reads CSV, JSON, and JSONL files from a /data/raw/ directory
2. Normalize all date fields to ISO 8601 (YYYY-MM-DD)
3. Standardize currency fields to a numeric float and a separate currency_code column
4. Deduplicate records using a deterministic key (document your key choice)
5. Handle nulls explicitly: impute, drop, or flag — justify each decision
6. Output clean data to /data/processed/ as Parquet files (one per entity)

PART 2 — DATA ENRICHMENT VIA EXCHANGERATE API
1. Integrate with a free ExchangeRate API (e.g., https://open.er-api.com/v6/latest/{base})
2. Convert all order amounts to USD using the exchange rate at the order date
3. Implement retry logic with exponential backoff (max 3 retries, 2s base delay)
4. Cache API responses to /data/cache/ keyed by date to avoid redundant calls
5. Handle API failures gracefully: log the error, mark the record with enrichment_status="failed"

PART 3 — HANDLING INCONSISTENCIES
1. Create a data_quality_report.json in /data/processed/ that catalogs:
   - Total records per entity
   - Count and % of nulls per field
   - Count of duplicates found and removed
   - Count of enrichment failures
2. For each inconsistency type listed in <input_data_description>, document in prompts.md:
   - How it was detected
   - The resolution strategy chosen
   - Why that strategy was preferred over alternatives

PART 4 — DATA MODELING
Design a star schema with these entities:
- dim_customers (customer_id PK, name, email, country, created_at)
- dim_products (product_id PK, name, category, base_price_usd)
- dim_dates (date_id PK, date, year, month, day, day_of_week)
- fact_orders (order_id PK, customer_id FK, product_id FK, date_id FK,
               quantity, unit_price_usd, total_amount_usd, currency_original,
               amount_original, exchange_rate, enrichment_status)
Store the final model as SQLite (for portability) at /data/warehouse/ecommerce.db

PART 5 — DATA PIPELINE
1. Build a pipeline orchestrated by a single entry point: pipeline/run.py
2. The pipeline must be idempotent: running it twice produces the same result
3. Each stage (ingest, clean, enrich, model) is a separate Python module under pipeline/stages/
4. Log start time, end time, and record counts for each stage using structured JSON logs
5. The pipeline must accept a --dry-run flag that validates inputs without writing outputs

PART 6 — API LAYER (FastAPI)
Implement the following endpoints with proper HTTP status codes and Pydantic response models:

GET /customers
  - Query params: country (optional filter), limit (default 100, max 1000), offset (default 0)
  - Response: { "total": int, "items": [CustomerSchema] }

GET /customers/{customer_id}
  - Response: CustomerSchema or 404

GET /orders
  - Query params: customer_id (optional), date_from, date_to, status, limit, offset
  - Response: { "total": int, "items": [OrderSchema] }

GET /orders/{order_id}
  - Response: OrderSchema or 404

GET /metrics
  - Response: {
      "total_orders": int,
      "total_revenue_usd": float,
      "avg_order_value_usd": float,
      "top_countries_by_revenue": [{ "country": str, "revenue_usd": float }],
      "orders_by_status": { "status": count },
      "enrichment_success_rate": float
    }

Architecture rules:
- Use a repository pattern: api/repositories/ handles all DB queries
- Use api/schemas/ for Pydantic models (separate request and response schemas)
- Use api/routers/ for route definitions (one file per resource)
- api/main.py only wires routers together — no business logic there

PART 7 — CONTAINERIZATION
1. Write a multi-stage Dockerfile:
   - Stage 1 (builder): copy pyproject.toml, install dependencies with pip install ., copy source
   - Stage 2 (runtime): copy only what's needed from the builder, run as non-root user
2. Write a docker-compose.yml that:
   - Service "pipeline": runs the data pipeline, mounts /data as a volume
   - Service "api": runs FastAPI on port 8000, depends on pipeline completion
3. Expose a health check endpoint at GET /health in the API

PART 8 — CI/CD PIPELINE (GitHub Actions)
Create .github/workflows/pipeline.yml that:
1. Triggers on push to main and on pull requests
2. Jobs (in order):
   a. lint: ruff check . (fail fast)
   b. test: pytest tests/ with coverage report (minimum 80% coverage)
   c. pipeline: docker compose run pipeline
   d. api-smoke-test: start API container, call GET /health and GET /metrics,
      assert HTTP 200 responses
3. Each job must be independently runnable locally using the same commands

PART 9 — OBSERVABILITY
1. Use Python's structlog library for structured JSON logging
2. Every log entry must include: timestamp, level, stage, event, and duration_ms where applicable
3. The API must log every request with: method, path, status_code, duration_ms
4. Pipeline failures must log: stage, error_type, error_message, and record_count_at_failure
5. Add a GET /logs/summary endpoint that returns the last 100 pipeline run log entries from a
   log file at /data/logs/pipeline.jsonl
</challenge_requirements>

<technical_constraints>
- Python 3.11+
- FastAPI + Uvicorn for the API layer
- SQLite for the data warehouse (no external database dependency)
- Pandas or Polars for data transformation (choose one and justify in prompts.md)
- Pydantic v2 for schema validation
- structlog for logging
- pytest for tests
- ruff for linting
- pyproject.toml (PEP 517/518) for dependency and project metadata management — no requirements.txt
- Docker + Docker Compose for containerization
- GitHub Actions for CI/CD
- No cloud service dependencies — must run fully offline except for the ExchangeRate API
</technical_constraints>

<output_format>
Produce the full project in this directory structure:

ecommerce_data_pipeline/
├── data/
│   ├── raw/                   # Input files go here (not committed)
│   ├── processed/             # Cleaned Parquet files
│   ├── cache/                 # API response cache
│   ├── warehouse/             # SQLite database
│   └── logs/                  # Structured pipeline logs
├── pipeline/
│   ├── __init__.py
│   ├── run.py                 # CLI entry point
│   ├── config.py              # Paths, constants, env vars
│   └── stages/
│       ├── ingest.py
│       ├── clean.py
│       ├── enrich.py
│       └── model.py
├── api/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py            # SQLite connection setup
│   ├── routers/
│   │   ├── customers.py
│   │   ├── orders.py
│   │   ├── metrics.py
│   │   └── logs.py
│   ├── repositories/
│   │   ├── customer_repo.py
│   │   └── order_repo.py
│   └── schemas/
│       ├── customer.py
│       └── order.py
├── tests/
│   ├── test_pipeline/
│   │   ├── test_ingest.py
│   │   ├── test_clean.py
│   │   └── test_enrich.py
│   └── test_api/
│       ├── test_customers.py
│       ├── test_orders.py
│       └── test_metrics.py
├── .github/
│   └── workflows/
│       └── pipeline.yml
├── Dockerfile
├── docker-compose.yml
├── Makefile                   # Targets: pipeline, test, api, lint, docker-build
├── pyproject.toml             # PEP 517/518: dependencies, tool config (ruff, pytest, coverage)
├── prompts.md                 # Document all AI prompts and technical decisions
└── README.md

pyproject.toml must include:
- [project] section with name, version, requires-python = ">=3.11", and all runtime dependencies
- [project.scripts] entry point: ecommerce-pipeline = "pipeline.run:main"
- [tool.pytest.ini_options] with testpaths = ["tests"] and coverage settings
- [tool.ruff] with line-length, select, and ignore rules
- [tool.ruff.lint] with at minimum E, F, I (isort), and UP (pyupgrade) rule sets

For each file you create, implement it completely — no placeholder comments like "# TODO".
</output_format>

<success_criteria>
Before finishing, verify your implementation against each criterion:

[ ] Pipeline runs end-to-end with: python pipeline/run.py
[ ] Pipeline is idempotent (run twice → same output)
[ ] --dry-run flag works without writing files
[ ] All 3 API resources return correct paginated responses
[ ] GET /metrics returns all required fields with correct types
[ ] GET /health returns HTTP 200
[ ] Docker Compose: docker compose up runs both pipeline and API cleanly
[ ] pytest passes with ≥80% coverage
[ ] ruff check . returns zero errors
[ ] GitHub Actions workflow runs all 4 jobs: lint → test → pipeline → api-smoke-test
[ ] Every pipeline stage emits structured JSON logs
[ ] prompts.md documents every data inconsistency decision and key technical choice
[ ] README.md contains: local setup, Docker setup, pipeline execution, API access,
    and explanation of 3+ non-obvious technical decisions
</success_criteria>

Now implement the full solution step by step, starting with the project structure and
moving through each part in order. After completing each part, briefly confirm what was
built and what comes next before proceeding.
```
