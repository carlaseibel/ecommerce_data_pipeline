"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    exchange_rate_api_url: str
    exchange_rate_api_key: str
    warehouse_path: Path
    raw_data_dir: Path
    validations_dir: Path
    log_level: str

    @property
    def schema_path(self) -> Path:
        return REPO_ROOT / "sql" / "schema.sql"


def _resolve(env_name: str, default: str) -> Path:
    raw = os.environ.get(env_name, default)
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


def load() -> Config:
    return Config(
        exchange_rate_api_url=os.environ.get(
            "EXCHANGE_RATE_API_URL", "https://v6.exchangerate-api.com/v6"
        ),
        exchange_rate_api_key=os.environ.get("EXCHANGE_RATE_API_KEY", ""),
        warehouse_path=_resolve("WAREHOUSE_PATH", "data/warehouse.sqlite"),
        raw_data_dir=_resolve("RAW_DATA_DIR", "raw_data"),
        validations_dir=_resolve("VALIDATIONS_DIR", "validations"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
