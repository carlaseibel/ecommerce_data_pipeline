"""End-to-end pipeline run on fixture data; asserts every checkpoint passed."""

from __future__ import annotations

from pathlib import Path

from src.pipeline import (
    enrich_exchange_rates,
    ingest_customers,
    ingest_events,
    ingest_orders,
    load_warehouse,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_full_pipeline(tmp_warehouse, validations_dir, fake_exchange_client) -> None:
    raw_dir = REPO_ROOT / "raw_data"
    run_id = "test-run"

    ingest_customers.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    ingest_orders.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    ingest_events.run(tmp_warehouse, raw_dir, validations_dir, run_id)
    enrich_exchange_rates.run(tmp_warehouse, fake_exchange_client, validations_dir, run_id)
    load_warehouse.run(tmp_warehouse, run_id)

    customers = tmp_warehouse.execute("SELECT customer_id FROM customers").fetchall()
    assert len(customers) == 6  # 7 raw rows, 1 duplicate dropped

    orders = tmp_warehouse.execute(
        "SELECT order_id, amount_usd FROM orders ORDER BY order_id"
    ).fetchall()
    order_ids = [r["order_id"] for r in orders]
    assert order_ids == ["O1001", "O1002"]
    o1001 = next(r for r in orders if r["order_id"] == "O1001")
    assert round(o1001["amount_usd"], 2) == 50.10

    events = tmp_warehouse.execute("SELECT event_id, event_type FROM events").fetchall()
    event_ids = sorted(r["event_id"] for r in events)
    assert event_ids == ["E1", "E2", "E3", "E5"]
    e5 = next(r for r in events if r["event_id"] == "E5")
    assert e5["event_type"] == "login"

    dq = tmp_warehouse.execute(
        "SELECT stage, success FROM data_quality_runs WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    assert len(dq) == 4
    assert all(row["success"] == 1 for row in dq)

    staging_count = tmp_warehouse.execute(
        "SELECT COUNT(*) FROM staging_orders"
    ).fetchone()[0]
    assert staging_count == 0
