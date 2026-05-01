"""Data-quality validator: applies declarative rules from validations/*.json to a DataFrame."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class CheckpointResult:
    success: bool
    evaluated: int
    succeeded: int
    validation_id: str
    failures: list[str]


def _check_column_exists(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    if col not in df.columns:
        return f"column {col!r} missing"
    return None


def _check_not_null(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    nulls = df[col].isna().sum()
    if nulls:
        return f"{col!r} has {nulls} null value(s)"
    return None


def _check_unique(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    dup = df[col].duplicated().sum()
    if dup:
        return f"{col!r} has {dup} duplicate value(s)"
    return None


def _check_between(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    lo = rule.get("min")
    hi = rule.get("max")
    series = df[col].dropna()
    if lo is not None:
        bad = series[series < lo] if not rule.get("strict_min") else series[series <= lo]
        if not bad.empty:
            return f"{col!r} has {len(bad)} value(s) below min={lo}"
    if hi is not None:
        bad = series[series > hi] if not rule.get("strict_max") else series[series >= hi]
        if not bad.empty:
            return f"{col!r} has {len(bad)} value(s) above max={hi}"
    return None


def _check_in_set(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    allowed = set(rule["values"])
    bad = df[~df[col].isin(allowed) & df[col].notna()]
    if not bad.empty:
        offending = sorted(bad[col].unique())[:5]
        return f"{col!r} has {len(bad)} value(s) outside set; e.g. {offending}"
    return None


def _check_matches_strftime(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    fmt = rule["format"]
    bad = 0
    for v in df[col].dropna():
        try:
            datetime.strptime(str(v), fmt)
        except ValueError:
            bad += 1
    if bad:
        return f"{col!r} has {bad} value(s) not matching {fmt!r}"
    return None


def _check_matches_regex(df: pd.DataFrame, rule: dict) -> str | None:
    col = rule["column"]
    pattern = re.compile(rule["regex"])
    bad = df[col].dropna().astype(str).map(lambda v: not bool(pattern.match(v))).sum()
    if bad:
        return f"{col!r} has {bad} value(s) not matching {rule['regex']!r}"
    return None


_CHECKS: dict[str, Callable[[pd.DataFrame, dict], str | None]] = {
    "column_exists": _check_column_exists,
    "not_null": _check_not_null,
    "unique": _check_unique,
    "between": _check_between,
    "in_set": _check_in_set,
    "matches_strftime": _check_matches_strftime,
    "matches_regex": _check_matches_regex,
}


def run_checkpoint(
    validations_dir: Path,
    checkpoint_name: str,
    suite_name: str,
    df: pd.DataFrame,
) -> CheckpointResult:
    spec_path = validations_dir / f"{suite_name}.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    rules = spec.get("rules", [])

    failures: list[str] = []
    succeeded = 0
    for rule in rules:
        check = _CHECKS.get(rule["type"])
        if check is None:
            raise ValueError(f"unknown rule type: {rule['type']}")
        msg = check(df, rule)
        if msg is None:
            succeeded += 1
        else:
            failures.append(f"[{rule['type']}] {msg}")

    return CheckpointResult(
        success=not failures,
        evaluated=len(rules),
        succeeded=succeeded,
        validation_id=uuid.uuid4().hex[:12],
        failures=failures,
    )


def record_run(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    checkpoint: str,
    result: CheckpointResult,
    started_at: datetime,
    duration_ms: int,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO data_quality_runs
            (run_id, stage, checkpoint, success, evaluated, succeeded,
             started_at, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            stage,
            checkpoint,
            int(result.success),
            result.evaluated,
            result.succeeded,
            started_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_ms,
        ),
    )
    conn.commit()
