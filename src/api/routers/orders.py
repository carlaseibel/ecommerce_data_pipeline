"""GET /orders — paginated order listing with customer_id / status / currency filters."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from src.api.deps import get_db
from src.api.schemas import Order, OrderListResponse

router = APIRouter()


@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    customer_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> OrderListResponse:
    clauses: list[str] = []
    params: list = []
    if customer_id is not None:
        clauses.append("customer_id = ?")
        params.append(customer_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status.lower())
    if currency is not None:
        clauses.append("currency_original = ?")
        params.append(currency.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = conn.execute(f"SELECT COUNT(*) FROM orders {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT order_id, customer_id, amount_original, currency_original, "
        f"exchange_rate, amount_usd, status, order_date "
        f"FROM orders {where} ORDER BY order_date, order_id LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()

    return OrderListResponse(
        items=[Order(**dict(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
