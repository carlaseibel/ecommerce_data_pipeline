"""Pydantic response models for /customers, /orders, /metrics, /data-quality."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class Customer(BaseModel):
    customer_id: int
    name: str | None
    email: str
    country: str | None
    created_at: date


class CustomerListResponse(BaseModel):
    items: list[Customer]
    total: int
    limit: int
    offset: int


class Order(BaseModel):
    order_id: str
    customer_id: int
    amount_original: float
    currency_original: str
    exchange_rate: float
    amount_usd: float
    status: str
    order_date: date


class OrderListResponse(BaseModel):
    items: list[Order]
    total: int
    limit: int
    offset: int


class RevenuePerCustomer(BaseModel):
    customer_id: int
    revenue_usd: float


class CountryStats(BaseModel):
    country: str
    order_count: int
    avg_amount_usd: float


class FunnelEntry(BaseModel):
    customer_id: int
    logins: int
    purchases: int


class MetricsResponse(BaseModel):
    revenue_per_customer: list[RevenuePerCustomer]
    country_stats: list[CountryStats]
    event_funnel: list[FunnelEntry]


class DataQualityRun(BaseModel):
    stage: str
    checkpoint: str
    success: bool
    evaluated: int
    succeeded: int
    started_at: datetime
    duration_ms: int


class DataQualityResponse(BaseModel):
    run_id: str | None
    overall_success: bool
    stages: list[DataQualityRun]
