"""GET /data-quality — latest GX checkpoint summary per stage from data_quality_runs."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.api.deps import get_db
from src.api.schemas import DataQualityResponse, DataQualityRun

router = APIRouter()


@router.get("/data-quality", response_model=DataQualityResponse)
def get_data_quality(conn: sqlite3.Connection = Depends(get_db)) -> DataQualityResponse:
    latest = conn.execute(
        "SELECT run_id FROM data_quality_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return DataQualityResponse(run_id=None, overall_success=False, stages=[])

    run_id = latest[0]
    rows = conn.execute(
        """
        SELECT stage, checkpoint, success, evaluated, succeeded, started_at, duration_ms
        FROM data_quality_runs
        WHERE run_id = ?
        ORDER BY started_at
        """,
        (run_id,),
    ).fetchall()

    stages = [
        DataQualityRun(
            stage=r["stage"],
            checkpoint=r["checkpoint"],
            success=bool(r["success"]),
            evaluated=r["evaluated"],
            succeeded=r["succeeded"],
            started_at=r["started_at"],
            duration_ms=r["duration_ms"],
        )
        for r in rows
    ]
    return DataQualityResponse(
        run_id=run_id,
        overall_success=all(s.success for s in stages),
        stages=stages,
    )
