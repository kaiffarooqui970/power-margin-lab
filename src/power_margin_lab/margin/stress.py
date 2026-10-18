"""Stress-period (SP) component: unfiltered historical scenarios from a fixed stressed window.

Only scenarios ending on or before the evaluation date are used (no look-ahead), so the SP
component builds up during the window itself and is unavailable before it starts.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from .fhs import empirical_quantile, portfolio_losses, unfiltered_scenarios


def stress_window(dates: list[date], t: int, start: date, end: date) -> np.ndarray:
    return np.array([i for i in range(t + 1) if start <= dates[i] <= end], dtype=int)


def stress_var(r: np.ndarray, dates: list[date], t: int, exposure: np.ndarray, cfg: dict,
               mpor: int) -> float:
    idx = stress_window(dates, t, cfg["start"], cfg["end"])
    if len(idx) < cfg["min_obs"]:
        return float("nan")
    scen = unfiltered_scenarios(r, idx, mpor)
    if len(scen.returns) < cfg["min_obs"]:
        return float("nan")
    return max(empirical_quantile(portfolio_losses(scen.returns, exposure), cfg["confidence"]),
               0.0)
