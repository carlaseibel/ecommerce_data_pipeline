"""Stage 2: load raw_data/orders.json → staging_orders table, gated by orders_clean_checkpoint."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.common import data_quality, db
from src.common.logging import get_logger

STAGE = "ingest_orders"
CHECKPOINT = "orders_clean_checkpoint"
SUITE = "orders_clean"

_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y")


def _parse_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _existing_customer_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT customer_id FROM customers")}


def run(conn: sqlite3.Connection, raw_dir: Path, validations_dir: Path, run_id: str) -> None:
    log = get_logger(STAGE)
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()

    db.truncate(conn, "staging_orders")

    raw = json.loads((raw_dir / "orders.json").read_text(encoding="utf-8"))
    customer_ids = _existing_customer_ids(conn)

    cleaned: list[dict] = []
    quarantined = 0

    for row in raw:
        order_id = row.get("order_id")
        cid = row.get("customer_id")
        amount = row.get("amount")
        currency = row.get("currency")
        status = row.get("status")
        order_date = _parse_date(row.get("order_date"))

        reason: str | None = None
        if cid is None:
            reason = "customer_id_null"
        elif int(cid) not in customer_ids:
            reason = "customer_id_orphan"
        elif not isinstance(amount, (int, float)) or amount < 0:
            reason = "amount_negative_or_invalid"
        elif order_date is None:
            reason = "order_date_unparseable"

        if reason is not None:
            log.warning(
                "Quarantined row",
                extra={"run_id": run_id, "record_id": order_id, "reason": reason},
            )
            data_quality.quarantine(conn, run_id, STAGE, order_id, reason, row)
            quarantined += 1
            continue

        cleaned.append(
            {
                "order_id": order_id,
                "customer_id": int(cid),
                "amount_original": float(amount),
                "currency_original": str(currency).upper(),
                "status": str(status).lower(),
                "order_date": order_date,
            }
        )

    df = pd.DataFrame(
        cleaned,
        columns=[
            "order_id",
            "customer_id",
            "amount_original",
            "currency_original",
            "status",
            "order_date",
        ],
    )

    dq_t0 = time.perf_counter()
    result = data_quality.run_checkpoint(validations_dir, CHECKPOINT, SUITE, df)
    dq_ms = int((time.perf_counter() - dq_t0) * 1000)
    data_quality.record_run(conn, run_id, STAGE, CHECKPOINT, result, started_at, dq_ms)

    if not result.success:
        log.error(
            "Checkpoint failed",
            extra={
                "run_id": run_id,
                "checkpoint": CHECKPOINT,
                "validation_id": result.validation_id,
                "expectations_evaluated": result.evaluated,
                "expectations_succeeded": result.succeeded,
            },
        )
        raise RuntimeError(f"{CHECKPOINT} failed")

    rows = [
        (
            r.order_id,
            r.customer_id,
            r.amount_original,
            r.currency_original,
            r.status,
            r.order_date,
        )
        for r in df.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO staging_orders "
        "(order_id, customer_id, amount_original, currency_original, status, order_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()

    duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "Stage complete",
        extra={
            "run_id": run_id,
            "records_loaded": len(rows),
            "records_quarantined": quarantined,
            "duration_ms": duration_ms,
        },
    )
    log.info(
        "Checkpoint passed",
        extra={
            "run_id": run_id,
            "checkpoint": CHECKPOINT,
            "validation_id": result.validation_id,
            "expectations_evaluated": result.evaluated,
            "expectations_succeeded": result.succeeded,
            "duration_ms": dq_ms,
        },
    )
