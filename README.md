# Ecommerce Data Pipeline

Containerized ecommerce pipeline that ingests local CSV/JSON/JSONL, validates each stage with
Great Expectations, enriches orders with live exchange rates, loads a SQLite warehouse, and
serves analytics through FastAPI.

Architecture: see [`docs/data_architecture.md`](docs/data_architecture.md).
Decision log: see [`prompts.md`](prompts.md).

## Run locally

```bash
make install         # install deps in current Python env
make lint            # ruff
make test            # pytest
make build           # docker compose build
make pipeline        # one-shot pipeline run via docker compose
make api             # start the API at http://localhost:8000
make api-stop        # stop the API
```

Direct compose equivalents (no Make required):

```bash
docker compose build
docker compose run --rm pipeline
docker compose up -d api
docker compose down
```

## Endpoints

- `GET /healthz`
- `GET /customers`
- `GET /orders`
- `GET /metrics`
- `GET /data-quality`
