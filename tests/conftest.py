"""Shared pytest fixtures: tmp SQLite warehouse, fake exchange API, validations dir."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.common import db

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tmp_warehouse(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "warehouse.sqlite")
    db.bootstrap(conn, REPO_ROOT / "sql" / "schema.sql")
    yield conn
    conn.close()


@pytest.fixture
def validations_dir() -> Path:
    return REPO_ROOT / "validations"


class FakeExchangeRateClient:
    def __init__(self, rates: dict[str, float] | None = None):
        self._rates = rates or {"USD": 1.0, "BRL": 0.20, "EUR": 1.10}

    def fetch_rates_to_usd(self, currencies: list[str]) -> dict[str, float]:
        return {c: self._rates[c] for c in currencies if c in self._rates}


@pytest.fixture
def fake_exchange_client() -> FakeExchangeRateClient:
    return FakeExchangeRateClient()
