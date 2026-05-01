.PHONY: install lint test build pipeline api api-stop api-smoke clean

install:
	pip install -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

test:
	pytest tests/

build:
	docker compose build

pipeline:
	docker compose run --rm pipeline

api:
	docker compose up -d api
	@echo "API at http://localhost:8000"

api-stop:
	docker compose down

api-smoke:
	docker compose up -d --wait api
	curl -fsS http://localhost:8000/healthz
	curl -fsS http://localhost:8000/data-quality
	curl -fsS "http://localhost:8000/customers?limit=1"
	docker compose down

clean:
	rm -rf data/*.sqlite
	find . -type d -name __pycache__ -exec rm -rf {} +
