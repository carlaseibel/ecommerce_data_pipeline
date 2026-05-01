"""FastAPI dependency providers: SQLite connection per request."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from src.common import config, db


def get_db() -> Iterator[sqlite3.Connection]:
    cfg = config.load()
    conn = db.connect(cfg.warehouse_path)
    try:
        yield conn
    finally:
        conn.close()
