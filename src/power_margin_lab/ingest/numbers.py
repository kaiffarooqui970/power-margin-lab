"""Strict number parsers, one per observed file convention (docs/DATA_INSPECTION.md).

The ECC files use three different conventions, so a lenient "parse anything" helper would
silently misread e.g. "1.234" (German thousands) as 1.234. Each parser accepts only its own
format and raises ValueError otherwise; callers turn errors into quarantine rows.
"""

from __future__ import annotations

import re

_DE = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")   # 3.993,84 | 893,62 | 12
_DOT = re.compile(r"^-?\d+(\.\d+)?$")                      # 0.73 | 14.42
_PCT = re.compile(r"^-?\d+(\.\d+)?%$")                     # 25.00%


def parse_de_decimal(s: str) -> float:
    """German format used by `scanningranges`: '.' thousands separator, ',' decimal mark."""
    s = s.strip()
    if not _DE.match(s):
        raise ValueError(f"not a German-format number: {s!r}")
    return float(s.replace(".", "").replace(",", "."))


def parse_dot_decimal(s: str) -> float:
    """Plain '.' decimal without thousands separators, used by `intercommodityspreads`."""
    s = s.strip()
    if not _DOT.match(s):
        raise ValueError(f"not a dot-decimal number: {s!r}")
    return float(s)


def parse_percent(s: str) -> float:
    """'25.00%' -> 0.25, used by `MarginBuffer`."""
    s = s.strip()
    if not _PCT.match(s):
        raise ValueError(f"not a percentage: {s!r}")
    return float(s[:-1]) / 100.0
