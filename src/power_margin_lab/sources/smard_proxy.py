"""PROXY source: synthetic futures tenor series built from SMARD day-ahead prices.

Construction (DECISIONS D-010 to D-013):
1. Daily baseload B(d): mean of the hourly DE-LU day-ahead prices of Berlin delivery day d.
2. Base risk factor X(t): trailing mean of B over the last `smoothing_days` calendar days,
   sampled on business days. A month future prices the average of a delivery month, so a
   30-day average is the simplest spot-derived stand-in for a front-month level; it removes
   most weekday/weather noise of single delivery days.
3. Base return r(t) = X(t) / X(t_prev) - 1.
4. Tenor return r_k(t) = s_k * r(t), with s_k = (scan/price)_k / (scan/price)_M1 taken from the
   ECC scanning ranges of the anchor date (relative risk per tenor as ECC sees it today).
5. Tenor level F_k(t) compounded from r_k, anchored to the REAL settlement price on the anchor
   date, so price levels are comparable to ECC's.

Consequences (stated in LIMITATIONS.md and quantified in the report):
- All tenors are driven by one factor, so cross-tenor correlation is 1 by construction. This
  overstates spread offsets in FHS (and would in SPAN credits if they were re-estimated).
- A trailing mean has autocorrelated returns (overlapping windows); spot-derived volatility is
  not futures volatility.
- Constant-maturity series: there are no contract rolls in the proxy.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ..model.products import business_days
from ..model.tenors import map_tenor
from .base import TENOR_COLUMNS, PriceSource


def base_factor(daily: pd.DataFrame, smoothing_days: int) -> pd.Series:
    """Trailing calendar-day mean of daily baseload, sampled on business days."""
    s = daily.set_index(pd.to_datetime(daily["delivery_day"]))["base_price"].sort_index()
    full = s.asfreq("D")
    if full.isna().any():
        raise ValueError("daily baseload series has gaps; cannot build proxy")
    x = full.rolling(smoothing_days, min_periods=smoothing_days).mean().dropna()
    bdays = pd.to_datetime(business_days(x.index[0].date(), x.index[-1].date()))
    x = x.reindex(bdays).dropna()
    if (x <= 0).any():
        raise ValueError("non-positive smoothed base price; relative returns undefined")
    x.index = x.index.date
    return x


def tenor_scales(anchor: pd.DataFrame) -> pd.Series:
    """s_k from anchor frame with columns tenor, price, scan_eur_per_mwh."""
    rel = anchor.set_index("tenor")["scan_eur_per_mwh"] / anchor.set_index("tenor")["price"]
    if "M1" not in rel.index:
        raise ValueError("anchor needs M1 for tenor scaling")
    return rel / rel["M1"]


class SmardProxySource(PriceSource):
    name = "smard_proxy"
    kind = "PROXY"

    def __init__(self, daily_base: pd.DataFrame, anchor: pd.DataFrame, anchor_date: date,
                 smoothing_days: int = 30, end: date | None = None):
        self.x = base_factor(daily_base, smoothing_days)
        if end is not None:
            self.x = self.x[self.x.index <= end]
        if anchor_date not in self.x.index:
            raise ValueError(f"anchor date {anchor_date} not in proxy business-day series")
        self.anchor = anchor.set_index("tenor")
        self.anchor_date = anchor_date
        self.scales = tenor_scales(anchor)

    def base_returns(self) -> pd.Series:
        return self.x / self.x.shift(1) - 1.0

    def tenor_series(self, tenors: list[str]) -> pd.DataFrame:
        r = self.base_returns()
        dates = list(r.index)
        ia = dates.index(self.anchor_date)
        frames = []
        for tenor in tenors:
            rk = (self.scales[tenor] * r).to_numpy()
            level = np.full(len(dates), np.nan)
            level[ia] = self.anchor.loc[tenor, "price"]
            for i in range(ia + 1, len(dates)):
                level[i] = level[i - 1] * (1.0 + rk[i])
            for i in range(ia - 1, -1, -1):
                level[i] = level[i + 1] / (1.0 + rk[i + 1])
            prods = [map_tenor(t, tenor) for t in dates]
            frames.append(pd.DataFrame({
                "trade_date": dates, "tenor": tenor,
                "product_id": [p.product_id for p in prods], "price": level, "ret_1d": rk,
                "delivery_hours": [p.delivery_hours for p in prods], "price_source": self.kind,
            }))
        return pd.concat(frames, ignore_index=True)[TENOR_COLUMNS]
