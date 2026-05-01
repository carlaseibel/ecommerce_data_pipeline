"""Stage 4: fetch USD rates for currencies in staging_orders, gated by exchange_rates_checkpoint."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.common import data_quality
from src.common.exchange_rate_client import ExchangeRateClient
from src.common.logging import get_logger

STAGE = "enrich_exchange_rates"
CHECKPOINT = "exchange_rates_checkpoint"
SUITE = "exchange_rates"


def _staged_currencies(conn: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT currency_original FROM staging_orders ORDER BY currency_original"
        )
    ]


def run(
    conn: sqlite3.Connection,
    client: ExchangeRateClient,
    validations_dir: Path,
    run_id: str,
) -> None:
    log = get_logger(STAGE)
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()

    currencies = _staged_currencies(conn)
    if not currencies:
        log.info("No currencies to fetch", extra={"run_id": run_id})
        return

    rates = client.fetch_rates_to_usd(currencies)
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    df = pd.DataFrame(
        [
            {"currency": cur, "rate_to_usd": rate, "fetched_at": fetched_at}
            for cur, rate in rates.items()
        ],
        columns=["currency", "rate_to_usd", "fetched_at"],
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

    rows = [(r.currency, r.rate_to_usd, r.fetched_at) for r in df.itertuples(index=False)]
    conn.executemany(
        "INSERT OR REPLACE INTO exchange_rates (currency, rate_to_usd, fetched_at) "
        "VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()

    duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "Fetched rates",
        extra={
            "run_id": run_id,
            "currencies": currencies,
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
