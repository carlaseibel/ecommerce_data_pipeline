"""FastAPI TestClient against a seeded warehouse; covers all four routers."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.deps import get_db
from src.pipeline import (
    enrich_exchange_rates,
    ingest_customers,
    ingest_events,
    ingest_orders,
    load_warehouse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def seeded_client(tmp_warehouse, validations_dir, fake_exchange_client) -> TestClient:
    raw_dir = REPO_ROOT / "raw_data"
    run_id = "api-test"
    ingest_customers.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    ingest_orders.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    ingest_events.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    enrich_exchange_rates.run(tmp_warehouse, fake_exchange_client, validations_dir, run_id)
    load_warehouse.run(tmp_warehouse, run_id)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: tmp_warehouse
    return TestClient(app)


def test_healthz(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_customers(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/customers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 6
    assert {c["customer_id"] for c in body["items"]} == {1, 2, 3, 4, 5, 6}


def test_customers_country_filter(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/customers", params={"country": "BR"})
    assert resp.status_code == 200
    body = resp.json()
    assert all(c["country"] == "BR" for c in body["items"])


def test_orders(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/orders")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {o["order_id"] for o in body["items"]} == {"O1001", "O1002"}


def test_metrics(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    revenue = {r["customer_id"]: r["revenue_usd"] for r in body["revenue_per_customer"]}
    assert round(revenue[1], 2) == 50.10  # O1001 only; O1002 was cancelled
    assert 2 not in revenue or revenue[2] == 0
    funnel = {f["customer_id"]: f for f in body["event_funnel"]}
    assert funnel[1]["logins"] == 1 and funnel[1]["purchases"] == 1


def test_data_quality(seeded_client: TestClient) -> None:
    resp = seeded_client.get("/data-quality")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_success"] is True
    stages = {s["stage"] for s in body["stages"]}
    assert stages == {
        "ingest_customers",
        "ingest_orders",
        "ingest_events",
        "enrich_exchange_rates",
    }
