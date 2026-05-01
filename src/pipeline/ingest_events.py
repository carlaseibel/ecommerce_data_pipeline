"""Stage 3: load raw_data/events.jsonl → events table, gated by events_checkpoint."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.common import data_quality
from src.common.logging import get_logger

STAGE = "ingest_events"
CHECKPOINT = "events_checkpoint"
SUITE = "events"


def _normalize_event_type(value: object) -> str:
    return str(value).lower().replace("_", "")


def _normalize_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _existing_customer_ids(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT customer_id FROM customers")}


def run(conn: sqlite3.Connection, raw_dir: Path, validations_dir: Path, run_id: str) -> None:
    log = get_logger(STAGE)
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    customer_ids = _existing_customer_ids(conn)
    cleaned: list[dict] = []
    skipped = 0

    with (raw_dir / "events.jsonl").open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                log.warning(
                    "JSON parse failure",
                    extra={"run_id": run_id, "record_id": f"line:{line_no}"},
                )
                skipped += 1
                continue

            event_id = row.get("event_id")
            cid = row.get("customer_id")
            timestamp = _normalize_timestamp(row.get("event_timestamp"))

            if timestamp is None:
                log.warning(
                    "Pre-filter dropped row: invalid timestamp",
                    extra={"run_id": run_id, "record_id": event_id},
                )
                skipped += 1
                continue
            if cid is None or int(cid) not in customer_ids:
                log.warning(
                    "Pre-filter dropped row: orphaned customer_id",
                    extra={"run_id": run_id, "record_id": event_id},
                )
                skipped += 1
                continue

            cleaned.append(
                {
                    "event_id": event_id,
                    "customer_id": int(cid),
                    "event_type": _normalize_event_type(row.get("event_type")),
                    "event_timestamp": timestamp,
                }
            )

    df = pd.DataFrame(
        cleaned,
        columns=["event_id", "customer_id", "event_type", "event_timestamp"],
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
        (r.event_id, r.customer_id, r.event_type, r.event_timestamp)
        for r in df.itertuples(index=False)
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO events "
        "(event_id, customer_id, event_type, event_timestamp) VALUES (?, ?, ?, ?)",
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
