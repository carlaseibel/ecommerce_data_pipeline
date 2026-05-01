"""Structured JSON logger factory used by every pipeline stage and the API."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

_OPTIONAL_FIELDS = (
    "run_id",
    "record_id",
    "records_loaded",
    "records_skipped",
    "duplicates_dropped",
    "validation_id",
    "checkpoint",
    "expectations_evaluated",
    "expectations_succeeded",
    "duration_ms",
    "currencies",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        payload: dict[str, Any] = {
            "level": record.levelname,
            "timestamp": ts,
            "stage": record.name,
            "message": record.getMessage(),
        }
        for key in _OPTIONAL_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_configured = False


def configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(stage: str) -> logging.Logger:
    configure()
    return logging.getLogger(stage)
