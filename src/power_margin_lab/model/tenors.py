"""Relative tenors (M1..Y2) and their mapping to actual contracts per trade date.

Mk / Qk / Yk = the k-th month / quarter / year contract whose delivery has not started and that
is still listed on the trade date. Contracts in delivery are therefore never part of a tenor
(D-007). When a listing is supplied (REAL / EEX data) it decides which contracts exist; otherwise
the calendar expiry rule in products.last_trading_day is used.

Returns are always computed within one contract: ret_1d(t) = F_p(t) / F_p(t_prev) - 1 where p is
the contract mapped at t. If p has no price at t_prev the return is missing - never F_p(t) over
the previous tenor contract's price.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

import pandas as pd

from .products import Product, _add_months, last_trading_day

TENOR_RE = re.compile(r"^([MQY])([1-9])$")


def parse_tenor(tenor: str) -> tuple[str, int]:
    m = TENOR_RE.match(tenor)
    if not m:
        raise ValueError(f"invalid tenor {tenor!r}")
    return m.group(1), int(m.group(2))


def candidate_products(t: date, delivery_type: str, n: int = 6) -> list[Product]:
    """Calendar candidates for a delivery type, starting with the period after t."""
    if delivery_type == "M":
        first = _add_months(date(t.year, t.month, 1), 1)
        return [Product(_add_months(first, i), "M") for i in range(n)]
    if delivery_type == "Q":
        q0 = date(t.year, 3 * ((t.month - 1) // 3) + 1, 1)
        return [Product(_add_months(q0, 3 * (i + 1)), "Q") for i in range(n)]
    return [Product(date(t.year + i + 1, 1, 1), "Y") for i in range(n)]


def map_tenor(t: date, tenor: str, listed: set[str] | None = None) -> Product | None:
    """Contract for `tenor` on trade date t; None if not enough listed contracts."""
    dtype, k = parse_tenor(tenor)
    found = 0
    for p in candidate_products(t, dtype):
        if p.delivery_start <= t:
            continue
        tradable = (p.product_id in listed) if listed is not None else (t <= last_trading_day(p))
        if tradable:
            found += 1
            if found == k:
                return p
    return None


def build_tenor_series(settlements: pd.DataFrame, tenors: Iterable[str],
                       price_source: str) -> pd.DataFrame:
    """Tenor series from contract-level settlements (columns trade_date, product_id, price).

    Returns columns: trade_date, tenor, product_id, price, ret_1d, delivery_hours, price_source.
    """
    s = settlements.copy()
    s["trade_date"] = pd.to_datetime(s["trade_date"]).dt.date
    prices = {(r.trade_date, r.product_id): r.price for r in s.itertuples(index=False)}
    dates = sorted(s["trade_date"].unique())
    listed_by_date = s.groupby("trade_date")["product_id"].apply(set).to_dict()
    rows = []
    for i, t in enumerate(dates):
        prev = dates[i - 1] if i > 0 else None
        for tenor in tenors:
            p = map_tenor(t, tenor, listed_by_date[t])
            if p is None:
                continue
            f_t = prices[(t, p.product_id)]
            f_prev = prices.get((prev, p.product_id)) if prev is not None else None
            ret = f_t / f_prev - 1.0 if f_prev not in (None, 0) else float("nan")
            rows.append((t, tenor, p.product_id, f_t, ret, p.delivery_hours, price_source))
    return pd.DataFrame(rows, columns=["trade_date", "tenor", "product_id", "price", "ret_1d",
                                       "delivery_hours", "price_source"])
