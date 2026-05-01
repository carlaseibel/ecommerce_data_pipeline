# Data Architecture Design Prompt — Ecommerce Pipeline

## Purpose

This prompt instructs an LLM to produce a complete data architecture design for the ecommerce
pipeline challenge. It follows Claude prompting best practices: role assignment, context before
instructions, XML tag separation, positive framing, concrete examples, and explicit output sections.

---

## Prompt

```xml
<system>
You are a Senior Data Engineer with 10+ years of experience designing production-grade data pipelines.
You specialize in data quality, clean architecture, API enrichment, and cloud-native infrastructure.
You write minimal, maintainable Python that solves exactly the problem at hand — no over-engineering.
Your architecture decisions are explicit, justified, and documented.
</system>

<context>
<challenge_summary>
Build a complete, containerized ecommerce data pipeline that:
1. Ingests and cleans local files (CSV, JSON, JSONL)
2. Enriches orders with live exchange rates from an external API
3. Models data for analytical consumption
4. Exposes processed data through a FastAPI application
5. Runs reproducibly inside Docker
6. Is automated via a GitHub Actions CI/CD pipeline
7. Emits structured, observable logs at every stage
</challenge_summary>

<raw_data_schema>
File: customers.csv
Fields: customer_id (int), name (str), email (str), country (str, ISO-2), created_at (date YYYY-MM-DD)
Known issues: 1 duplicate row (customer_id=3), 1 missing name, 1 missing country

File: orders.json
Fields: order_id (str), customer_id (int|null), amount (float), currency (str), status (str), order_date (str)
Known issues: null customer_id (1 row), orphaned customer_id=99 (not in customers), negative amount=-50.00,
  mixed-case status ["completed","CANCELLED","Completed"], two date formats (YYYY-MM-DD and DD-MM-YYYY),
  mixed currencies (BRL, USD, EUR)

File: events.jsonl
Fields: event_id (str), customer_id (int), event_type (str), event_timestamp (str ISO-8601)
Known issues: mixed event_type casing ["login","LOG_IN"], 1 invalid timestamp ("invalid_timestamp"),
  orphaned customer_id=99 (not in customers)
</raw_data_schema>

<enrichment_requirement>
Integrate the ExchangeRate API to convert all order amounts to a single base currency (USD).
The API call may fail, timeout, or return unexpected payloads — handle all cases gracefully.
Store the fetched exchange rate alongside the converted amount so the transformation is auditable.
</enrichment_requirement>

<constraints>
- Storage: SQLite (single file, no external server, Docker-friendly)
- Python 3.11+, FastAPI, pytest
- All pipeline stages must be re-runnable (idempotent)
- Structured JSON logs with: level, timestamp, stage, message, and optional record_id
- No features beyond what is explicitly required
</constraints>
</context>

<instructions>
Design a complete data architecture for this pipeline. Reason through each layer before specifying it.
Focus on: correctness of the data model, explicit handling of every known data issue, clean separation
of pipeline stages, and a FastAPI contract that is useful for analytics consumers.

Produce your design in the sections below. For each decision that is non-obvious, include a one-sentence
justification tagged as [WHY].
</instructions>

<output_format>
Respond using exactly these sections:

<project_structure>
Full directory tree of the project with a one-line purpose for each file.
</project_structure>

<data_quality_decisions>
A table with columns: Issue | Source File | Decision | Justification
Cover every known issue from the raw_data_schema. Be explicit — "discard", "impute", "normalize", or
"flag" are all valid choices with different trade-offs.
</data_quality_decisions>

<data_model>
Define the SQLite tables using SQL CREATE TABLE statements.
Include: primary keys, foreign keys, NOT NULL constraints, and index hints.
Tables must support these analytical queries without joins on raw text:
  - Total revenue per customer in USD
  - Order count and average amount per country
  - Event funnel (login → purchase) per customer
</data_model>

<pipeline_stages>
List each stage as: Stage Name → Input → Output → Key transformations → Error behavior
Stages must be: ingest_customers, ingest_orders, ingest_events, enrich_exchange_rates, load_warehouse
</pipeline_stages>

<api_contract>
For each FastAPI endpoint specify: method, path, query params, response schema (as a Pydantic model
skeleton), and one example response.
Required endpoints: GET /customers, GET /orders, GET /metrics
</api_contract>

<cicd_pipeline>
Describe the GitHub Actions workflow stages in order: what each job does, which commands it runs,
and what artifact it produces or validates. The same commands must work locally without modification.
</cicd_pipeline>

<observability_spec>
Define the structured log schema (JSON fields) and list one example log line per pipeline stage.
</observability_spec>
</output_format>

<examples>
<example_quality_decision>
Issue: Mixed-case status in orders.json ("completed", "CANCELLED", "Completed")
Decision: Normalize to lowercase on ingest
Justification: Downstream GROUP BY queries on status require consistent casing; lowercase is the
  least-surprise convention for enum-like fields.
</example_quality_decision>

<example_log_line>
{"level":"INFO","timestamp":"2024-01-15T10:23:01Z","stage":"ingest_customers","message":"Loaded 6 records, dropped 1 duplicate","records_loaded":6,"duplicates_dropped":1}
</example_log_line>
</examples>
```

---

## Prompt Engineering Rationale

| Technique | Applied as | Why |
|---|---|---|
| Role assignment in system prompt | Senior Data Engineer persona with explicit specializations | Anchors tone, precision, and the "no over-engineering" constraint |
| Data placed before instructions | `<context>` block with full schema appears before `<instructions>` | Up to 30% performance gain; Claude reads top-to-bottom |
| XML tags for content separation | `<context>`, `<raw_data_schema>`, `<instructions>`, `<output_format>` | Eliminates ambiguity about what is data vs. instructions vs. examples |
| Positive framing | "Normalize to lowercase" not "don't use mixed case" | Claude 4.x interprets negations more literally; positive framing is unambiguous |
| Concrete examples in `<examples>` | One quality decision example + one log line example | Anchors the output format for the two most free-form sections |
| Soft chain-of-thought nudge | "Reason through each layer before specifying it" | Avoids prescriptive steps that cap Claude's reasoning quality |
| Explicit output sections | Seven named XML output sections | Ensures completeness; each section maps to a verifiable requirement |
| Known ambiguities resolved in-prompt | `customer_id=99` orphan, negative amounts, null customer_id all named | Prevents Claude from silently dropping or mishandling edge cases |
| Idempotency stated explicitly | Listed in `<constraints>` | CI pipelines re-run stages; easy to miss if unstated |

---

## Output Verification Checklist

Use this checklist to validate the LLM response is complete and correct:

- [ ] Every issue in `raw_data_schema` has a row in `data_quality_decisions`
- [ ] SQL schema supports all three named analytical queries without raw-text joins
- [ ] All 5 pipeline stages are described with error behavior
- [ ] All 3 API endpoints have a Pydantic model skeleton and an example response
- [ ] CI/CD commands are copy-pasteable locally (no GitHub-specific env vars without fallbacks)
- [ ] Log schema includes at minimum: `level`, `timestamp`, `stage`, `message`
