"""Backtesting: breaches, Kupiec POF, Christoffersen independence, Basel traffic light.

A breach on day t: realised loss over (t, t+2] exceeds IM(t). Because consecutive 2-day
windows overlap, breaches are serially dependent by construction; the Christoffersen test
therefore tends to reject more often than for 1-day backtests (stated in METHODOLOGY.md).
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import chi2


def _xlogy(x: float, y: float) -> float:
    return 0.0 if x == 0 else x * math.log(y)


def kupiec_pof(n: int, x: int, p: float) -> tuple[float, float]:
    """Kupiec (1995) proportion-of-failures LR test. Returns (LR, p-value)."""
    if n == 0:
        return float("nan"), float("nan")
    phat = x / n
    ll0 = _xlogy(n - x, 1 - p) + _xlogy(x, p)
    ll1 = _xlogy(n - x, 1 - phat) + _xlogy(x, phat)
    lr = max(-2 * (ll0 - ll1), 0.0)
    return lr, float(chi2.sf(lr, 1))


def christoffersen_independence(hits: np.ndarray) -> tuple[float, float]:
    """Christoffersen (1998) Markov independence LR test. Returns (LR, p-value)."""
    h = np.asarray(hits, dtype=int)
    if len(h) < 2:
        return float("nan"), float("nan")
    prev, cur = h[:-1], h[1:]
    n00 = int(np.sum((prev == 0) & (cur == 0)))
    n01 = int(np.sum((prev == 0) & (cur == 1)))
    n10 = int(np.sum((prev == 1) & (cur == 0)))
    n11 = int(np.sum((prev == 1) & (cur == 1)))
    if n01 + n11 == 0:
        return 0.0, 1.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    pi01 = n01 / (n00 + n01) if n00 + n01 else 0.0
    pi11 = n11 / (n10 + n11) if n10 + n11 else 0.0
    ll0 = _xlogy(n00 + n10, 1 - pi) + _xlogy(n01 + n11, pi)
    ll1 = (_xlogy(n00, 1 - pi01) + _xlogy(n01, pi01) + _xlogy(n10, 1 - pi11)
           + _xlogy(n11, pi11))
    lr = max(-2 * (ll0 - ll1), 0.0)
    return lr, float(chi2.sf(lr, 1))


def traffic_light(breaches: int) -> str:
    """Basel zones for 250 observations at 99 %: green 0-4, yellow 5-9, red >= 10."""
    if breaches <= 4:
        return "green"
    return "yellow" if breaches <= 9 else "red"


def rolling_breach_max(hits: np.ndarray, window: int) -> int:
    h = np.asarray(hits, dtype=int)
    if len(h) < window:
        return int(h.sum())
    c = np.concatenate([[0], np.cumsum(h)])
    return int(np.max(c[window:] - c[:-window]))


def summarise(hits: np.ndarray, p: float, window: int) -> dict:
    hits = np.asarray(hits, dtype=int)
    n, x = len(hits), int(hits.sum())
    _, p_kup = kupiec_pof(n, x, p)
    _, p_chr = christoffersen_independence(hits)
    last = hits[-window:]
    worst = rolling_breach_max(hits, window)
    # Non-overlapping subsample (every 2nd day) removes the dependence created by overlapping
    # 2-day P&L windows; what remains is genuine clustering.
    sub = hits[::2]
    _, p_kup_no = kupiec_pof(len(sub), int(sub.sum()), p)
    _, p_chr_no = christoffersen_independence(sub)
    return {"n_obs": n, "breaches": x, "breach_rate": x / n if n else float("nan"),
            "expected": n * p, "kupiec_p": p_kup, "christoffersen_p": p_chr,
            "kupiec_p_nonoverlap": p_kup_no, "christoffersen_p_nonoverlap": p_chr_no,
            "breaches_last_250": int(last.sum()), "zone_last_250": traffic_light(int(last.sum())),
            "max_breaches_any_250": worst, "zone_worst_250": traffic_light(worst)}
