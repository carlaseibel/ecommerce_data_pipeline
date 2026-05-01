"""GET /metrics — revenue per customer, country stats, event funnel."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from src.api.deps import get_db
from src.api.schemas import (
    CountryStats,
    FunnelEntry,
    MetricsResponse,
    RevenuePerCustomer,
)

router = APIRouter()

DbConn = Annotated[sqlite3.Connection, Depends(get_db)]


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(conn: DbConn) -> MetricsResponse:
    revenue = conn.execute(
        """
        SELECT customer_id, ROUND(SUM(amount_usd), 2) AS revenue_usd
        FROM orders
        WHERE status = 'completed'
        GROUP BY customer_id
        ORDER BY customer_id
        """
    ).fetchall()

    country = conn.execute(
        """
        SELECT c.country,
               COUNT(o.order_id)             AS order_count,
               ROUND(AVG(o.amount_usd), 2)   AS avg_amount_usd
        FROM orders o
        JOIN customers c USING (customer_id)
        WHERE c.country IS NOT NULL
        GROUP BY c.country
        ORDER BY c.country
        """
    ).fetchall()

    funnel = conn.execute(
        """
        SELECT customer_id,
               SUM(CASE WHEN event_type = 'login'    THEN 1 ELSE 0 END) AS logins,
               SUM(CASE WHEN event_type = 'purchase' THEN 1 ELSE 0 END) AS purchases
        FROM events
        GROUP BY customer_id
        ORDER BY customer_id
        """
    ).fetchall()

    return MetricsResponse(
        revenue_per_customer=[RevenuePerCustomer(**dict(r)) for r in revenue],
        country_stats=[CountryStats(**dict(r)) for r in country],
        event_funnel=[FunnelEntry(**dict(r)) for r in funnel],
    )
