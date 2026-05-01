"""GET /error-events — paginated drill-in for quarantined rows."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.api.schemas import ErrorEvent, ErrorEventListResponse

router = APIRouter()

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]


@router.get("/error-events", response_model=ErrorEventListResponse)
def list_error_events(
    conn: DbConn,
    run_id: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ErrorEventListResponse:
    clauses: list[str] = []
    params: list = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if stage is not None:
        clauses.append("stage = ?")
        params.append(stage)
    if reason is not None:
        clauses.append("reason = ?")
        params.append(reason)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = conn.execute(f"SELECT COUNT(*) FROM error_events {where}", tuple(params)).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, run_id, stage, source_record_id, reason, raw_payload, occurred_at "
        f"FROM error_events {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()

    return ErrorEventListResponse(
        items=[ErrorEvent(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
