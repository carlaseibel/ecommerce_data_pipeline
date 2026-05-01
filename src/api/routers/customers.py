"""GET /customers — paginated customer listing, optional country filter."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.api.schemas import Customer, CustomerListResponse

router = APIRouter()


@router.get("/customers", response_model=CustomerListResponse)
def list_customers(
    country: str | None = Query(default=None, min_length=2, max_length=2),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> CustomerListResponse:
    where = "WHERE country = ?" if country else ""
    params: tuple = (country,) if country else ()

    total = conn.execute(f"SELECT COUNT(*) FROM customers {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT customer_id, name, email, country, created_at "
        f"FROM customers {where} ORDER BY customer_id LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()

    return CustomerListResponse(
        items=[Customer(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
