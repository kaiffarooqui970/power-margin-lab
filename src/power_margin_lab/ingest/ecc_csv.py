"""Read ECC public CSV files (scanning ranges, margin buffer, inter-commodity spreads).

All files are read as strings; typing happens in the schema contract (contracts/validate.py)
with the file-specific number parser. File name dates are attached as calc_date / valid_date.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..contracts.validate import apply_contract, load_contract

NAME_RE = re.compile(r"^(?P<calc>\d{8})_(?P<kind>\w+?)_(?P<valid>\d{8})\.csv$")
GERMAN_BASE = ("DEBM", "DEBQ", "DEBY")


def file_dates(path: Path) -> tuple:
    m = NAME_RE.match(path.name)
    if not m:
        raise ValueError(f"unexpected ECC file name {path.name}")
    to_date = lambda s: datetime.strptime(s, "%Y%m%d").date()  # noqa: E731
    return to_date(m["calc"]), to_date(m["valid"])


def _read_str(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, encoding="ascii")


def _load(path: Path, contract_name: str, raw: pd.DataFrame | None = None):
    calc, valid = file_dates(path)
    raw = _read_str(path) if raw is None else raw
    df, quarantine, drift = apply_contract(raw, load_contract(contract_name), path.name)
    df.insert(0, "calc_date", calc)
    df.insert(1, "valid_date", valid)
    return df, quarantine, drift


def load_scanning_ranges(path: Path):
    return _load(path, "raw_ecc_scanning_range")


def load_margin_buffer(path: Path):
    return _load(path, "raw_ecc_margin_buffer")


def load_spread_credits(path: Path, commodities: tuple[str, ...] = GERMAN_BASE):
    """~1.1 M rows/day: filter on raw strings to pairs with both legs in `commodities` first."""
    raw = _read_str(path)
    raw = raw[raw["CombinedCommodityA"].isin(commodities)
              & raw["CombinedCommodityB"].isin(commodities)].reset_index(drop=True)
    return _load(path, "raw_ecc_spread_credit", raw)


def find_files(raw_ecc: Path, kind: str) -> list[Path]:
    return sorted(raw_ecc.glob(f"*/*_{kind}_*.csv"))
