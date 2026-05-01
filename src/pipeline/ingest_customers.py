"""Stage 1: load raw_data/customers.csv → customers table, gated by customers_checkpoint."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.common import data_quality
from src.common.logging import get_logger

STAGE = "ingest_customers"
CHECKPOINT = "customers_checkpoint"
SUITE = "customers"


def run(conn: sqlite3.Connection, raw_dir: Path, validations_dir: Path, run_id: str) -> None:
    log = get_logger(STAGE)
    started_at = datetime.now(UTC)
    t0 = time.perf_counter()

    df = pd.read_csv(raw_dir / "customers.csv", dtype={"customer_id": "Int64"})

    dup_mask = df.duplicated(subset=["customer_id"], keep="first")
    for dup_row in df[dup_mask].to_dict(orient="records"):
        log.warning(
            "Quarantined row",
            extra={
                "run_id": run_id,
                "record_id": dup_row.get("customer_id"),
                "reason": "customer_id_duplicate",
            },
        )
        data_quality.quarantine(
            conn, run_id, STAGE, dup_row.get("customer_id"), "customer_id_duplicate", dup_row
        )
    quarantined = int(dup_mask.sum())

    df = df[~dup_mask].reset_index(drop=True)

    df["customer_id"] = df["customer_id"].astype(int)
    for col in ("name", "email", "country"):
        df[col] = df[col].where(df[col].notna(), None)
        if col == "email" or col == "name":
            df[col] = df[col].astype("object")

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
        (int(r.customer_id), r.name, r.email, r.country, r.created_at)
        for r in df.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO customers (customer_id, name, email, country, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
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
