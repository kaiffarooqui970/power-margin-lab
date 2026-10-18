"""YAML schema contracts: header drift detection, typed parsing, row validation, quarantine.

A contract (contracts/schemas/<name>.yml) lists the expected source header and, per target
column, the source column, a parser, nullability and value constraints. `apply_contract`
returns (valid, quarantine, drift):

- drift: missing/unexpected header columns. Missing required columns raise ContractError
  (the file cannot be interpreted); unexpected columns are logged and ignored.
- quarantine: one row per rejected record with the raw values (JSON) and the first reason.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from ..ingest.numbers import parse_de_decimal, parse_dot_decimal, parse_percent

SCHEMA_DIR = Path(__file__).parent / "schemas"


class ContractError(ValueError):
    pass


def _parse_date(fmt: str):
    return lambda s: datetime.strptime(s.strip(), fmt).date()


PARSERS = {
    "str": lambda s: s.strip(),
    "int": lambda s: int(s.strip()),
    "float_de": parse_de_decimal,
    "float_dot": parse_dot_decimal,
    "percent": parse_percent,
    "date_dmy": _parse_date("%d.%m.%Y"),
    "date_ymd": _parse_date("%Y%m%d"),
    "float": float,
}


def load_contract(name: str) -> dict:
    with open(SCHEMA_DIR / f"{name}.yml", encoding="utf-8") as f:
        contract = yaml.safe_load(f)
    for col, spec in contract["columns"].items():
        for key in ("min", "max", "exclusive_min"):
            if key in spec and not isinstance(spec[key], int | float):
                raise ContractError(f"{name}.{col}.{key} must be numeric, got {spec[key]!r}")
        if spec["type"] not in PARSERS:
            raise ContractError(f"{name}.{col}: unknown type {spec['type']!r}")
    return contract


def check_drift(contract: dict, columns: list[str], source_file: str) -> list[dict]:
    expected = contract["source_columns"]
    required = {spec["source"] for spec in contract["columns"].values()
                if not spec.get("derived")}
    missing = [c for c in expected if c not in columns]
    unexpected = [c for c in columns if c not in expected]
    events = []
    if missing or unexpected:
        events.append({"contract": contract["name"], "source_file": source_file,
                       "missing_columns": ",".join(missing),
                       "unexpected_columns": ",".join(unexpected),
                       "detected_at": datetime.now().isoformat(timespec="seconds")})
    hard = [c for c in missing if c in required]
    if hard:
        raise ContractError(f"{source_file}: required columns missing {hard}")
    return events


def _check(value, spec: dict) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None if spec.get("nullable", False) else "null not allowed"
    if "min" in spec and value < spec["min"]:
        return f"below min {spec['min']}"
    if "max" in spec and value > spec["max"]:
        return f"above max {spec['max']}"
    if "exclusive_min" in spec and value <= spec["exclusive_min"]:
        return f"not above {spec['exclusive_min']}"
    if "allowed" in spec and value not in spec["allowed"]:
        return "not in allowed set"
    if "regex" in spec and not re.match(spec["regex"], str(value)):
        return f"does not match {spec['regex']}"
    return None


def apply_contract(raw: pd.DataFrame, contract: dict, source_file: str
                   ) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Validate a raw frame of strings against `contract`."""
    drift = check_drift(contract, list(raw.columns), source_file)
    cols = contract["columns"]
    good, bad = [], []
    for rec in raw.to_dict("records"):
        out, reason = {}, None
        for target, spec in cols.items():
            src = rec.get(spec["source"])
            if src is None or (isinstance(src, float) and pd.isna(src)) or str(src).strip() == "":
                val = None
            else:
                try:
                    val = PARSERS[spec["type"]](str(src))
                except (ValueError, TypeError) as e:
                    reason = f"{target}: parse error ({e})"
                    break
            reason = _check(val, spec)
            if reason:
                reason = f"{target}: {reason}"
                break
            out[target] = val
        if reason:
            bad.append({"contract": contract["name"], "source_file": source_file,
                        "reason": reason, "raw_record": json.dumps(rec, default=str)})
        else:
            good.append(out)
    valid = pd.DataFrame(good, columns=list(cols))
    valid["source_file"] = source_file
    quarantine = pd.DataFrame(bad, columns=["contract", "source_file", "reason", "raw_record"])
    return valid, quarantine, drift
