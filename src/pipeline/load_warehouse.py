"""Stage 5: join staging_orders with exchange_rates → orders table; truncate staging."""

from __future__ import annotations

import sqlite3
import time

from src.common import db
from src.common.logging import get_logger

STAGE = "load_warehouse"


def run(conn: sqlite3.Connection, run_id: str) -> None:
    log = get_logger(STAGE)
    t0 = time.perf_counter()

    missing = conn.execute(
        """
        SELECT DISTINCT s.currency_original
        FROM staging_orders s
        LEFT JOIN exchange_rates r ON r.currency = s.currency_original
        WHERE r.currency IS NULL
        """
    ).fetchall()
    if missing:
        currencies = [row[0] for row in missing]
        log.error(
            "Missing exchange rates for staged currencies",
            extra={"run_id": run_id, "currencies": currencies},
        )
        raise RuntimeError(f"missing exchange rates for: {currencies}")

    cur = conn.execute(
        """
        INSERT OR REPLACE INTO orders
            (order_id, customer_id, amount_original, currency_original,
             exchange_rate, amount_usd, status, order_date)
        SELECT
            s.order_id,
            s.customer_id,
            s.amount_original,
            s.currency_original,
            r.rate_to_usd,
            s.amount_original * r.rate_to_usd,
            s.status,
            s.order_date
        FROM staging_orders s
        JOIN exchange_rates r ON r.currency = s.currency_original
        """
    )
    loaded = cur.rowcount
    conn.commit()

    db.truncate(conn, "staging_orders")

    duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "Stage complete",
        extra={
            "run_id": run_id,
            "records_loaded": loaded,
            "duration_ms": duration_ms,
        },
    )
