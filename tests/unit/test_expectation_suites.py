"""Validates every validation spec parses and references columns that exist in sql/schema.sql."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATIONS_DIR = REPO_ROOT / "validations"
SCHEMA_PATH = REPO_ROOT / "sql" / "schema.sql"


def _columns_for_table(schema_sql: str, table: str) -> set[str]:
    pattern = rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\);"
    match = re.search(pattern, schema_sql, re.DOTALL | re.IGNORECASE)
    if not match:
        return set()
    cols: set[str] = set()
    for line in match.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith(("PRIMARY KEY", "FOREIGN KEY")):
            continue
        token = line.split()[0]
        cols.add(token)
    return cols


SPEC_TO_TABLE = {
    "customers.json": "customers",
    "orders_clean.json": "staging_orders",
    "events.json": "events",
    "exchange_rates.json": "exchange_rates",
}


@pytest.mark.parametrize("spec_file, table", list(SPEC_TO_TABLE.items()))
def test_spec_columns_exist_in_schema(spec_file: str, table: str) -> None:
    spec = json.loads((VALIDATIONS_DIR / spec_file).read_text(encoding="utf-8"))
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    schema_cols = _columns_for_table(schema, table)
    assert schema_cols, f"no columns parsed for table {table}"

    for rule in spec["rules"]:
        col = rule.get("column")
        if col is None:
            continue
        assert col in schema_cols, (
            f"{spec_file}: rule references unknown column "
            f"{col!r} (table {table}, known: {sorted(schema_cols)})"
        )


def test_all_specs_parse() -> None:
    for path in VALIDATIONS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "name" in data
        assert isinstance(data.get("rules"), list)
