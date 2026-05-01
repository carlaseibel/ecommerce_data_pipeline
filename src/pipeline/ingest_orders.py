"""Stage 2: load raw_data/orders.json → staging_orders table, gated by orders_clean_checkpoint."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
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
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    db.truncate(conn, "staging_orders")

    raw = json.loads((raw_dir / "orders.json").read_text(encoding="utf-8"))
    customer_ids = _existing_customer_ids(conn)

    cleaned: list[dict] = []
    skipped = 0

    for row in raw:
        order_id = row.get("order_id")
        cid = row.get("customer_id")
        amount = row.get("amount")
        currency = row.get("currency")
        status = row.get("status")
        order_date = _parse_date(row.get("order_date"))

        if cid is None:
            log.warning(
                "Pre-filter dropped row: customer_id is null",
                extra={"run_id": run_id, "record_id": order_id},
            )
            skipped += 1
            continue
        if int(cid) not in customer_ids:
            log.warning(
                "Pre-filter dropped row: orphaned customer_id",
                extra={"run_id": run_id, "record_id": order_id},
            )
            skipped += 1
            continue
        if not isinstance(amount, (int, float)) or amount < 0:
            log.warning(
                "Pre-filter dropped row: negative or invalid amount",
                extra={"run_id": run_id, "record_id": order_id},
            )
            skipped += 1
            continue
        if order_date is None:
            log.warning(
                "Pre-filter dropped row: unparseable order_date",
                extra={"run_id": run_id, "record_id": order_id},
            )
            skipped += 1
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
            "records_skipped": skipped,
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
