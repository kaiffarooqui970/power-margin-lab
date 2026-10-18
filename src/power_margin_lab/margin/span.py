"""Simplified SPAN for outright German baseload futures, following ECC Derivative Market
Margining V1.19 (section numbers below refer to that document).

Two parts:
1. `smp_series`: the Single Margin Parameter (scanning range) formula of §4.1.2.1 / §5.1-5.3,
   used for SPAN-hist. M = p * sigma * sqrt(l) * R * (1 + b), W = 1, add-on a = 0.
2. `span_im`: portfolio SPAN for futures: 16-scenario scan risk per tier (§4.1.3), the
   intra-commodity charge (§4.1.4.2, zero for ECC's single-expiry power tiers) and
   inter-commodity / inter-tier credits (§4.1.4.3, ECC Guide to Margining p. 14).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# §4.1.3 Table 1: (price move as multiple of scan range, weight). Volatility moves are
# irrelevant for futures and omitted.
SCAN_POINTS: list[tuple[float, float]] = [
    (0.0, 1), (0.0, 1), (1 / 3, 1), (1 / 3, 1), (-1 / 3, 1), (-1 / 3, 1),
    (2 / 3, 1), (2 / 3, 1), (-2 / 3, 1), (-2 / 3, 1), (1.0, 1), (1.0, 1),
    (-1.0, 1), (-1.0, 1), (3.0, 0.33), (-3.0, 0.33),
]


# --- 1. Single Margin Parameter (SPAN-hist) --------------------------------------------------

def _ewma_window_sigma(window: np.ndarray, lam: float) -> float:
    """§5.1: sqrt(sum r_k^2 lam^k / sum lam^k), k = 1 is the most recent return."""
    k = np.arange(1, len(window) + 1)
    w = lam ** k
    return math.sqrt(float(np.sum(window[::-1] ** 2 * w) / np.sum(w)))


def smp_series(dates: list, returns: np.ndarray, cfg: dict) -> pd.DataFrame:
    """Relative SMP per date for one constant-maturity return series.

    Returns columns: trade_date, n_obs, sigma, R, b0, b1, b, smp_rel (fraction of price).
    smp_rel * price = SMP in EUR/MWh; times delivery hours = scanning range per lot.
    """
    lam, n_win = cfg["ewma_lambda"], cfg["lookback_returns"]
    alpha, rmin, rmax = cfg["alpha_r"], cfg["r_min"], cfg["r_max"]
    w, a, bmax, l_days = cfg["stress_weight_w"], cfg["buffer_a"], cfg["buffer_max"], \
        cfg["liquidation_days"]
    min_obs = cfg["min_obs_for_r"]

    r = np.asarray(returns, dtype=float)
    nz_mask = np.isfinite(r) & (r != 0.0)          # §5.1: only non-zero returns
    nz = r[nz_mask]
    nz_pos = np.cumsum(nz_mask)                    # number of non-zero returns up to each date

    # sigma at each non-zero estimation time j (window ends at j)
    sig_nz = np.array([_ewma_window_sigma(nz[max(0, j + 1 - n_win): j + 1], lam)
                       for j in range(len(nz))])

    rows = []
    sig_hist: list[float] = []                     # sigma series for sigma_min / sigma_max
    for i, t in enumerate(dates):
        n = int(nz_pos[i])
        if n < 20:
            rows.append((t, n, *([np.nan] * 6)))
            continue
        sigma = sig_nz[n - 1]
        lo = max(1, n - n_win)                     # z needs sigma at the previous estimation time
        z = nz[lo:n] / sig_nz[lo - 1:n - 1]
        if len(z) < min_obs:
            big_r = rmax                           # §5.2: fewer than 100 observations -> R_max
        else:
            r0 = 0.5 * (abs(np.quantile(z, alpha)) + abs(np.quantile(z, 1 - alpha)))
            big_r = min(max(r0, rmin), rmax)
        if n >= min_obs:
            sig_hist.append(sigma)
        smin = min(sig_hist) if sig_hist else sigma
        smax = max(sig_hist) if sig_hist else sigma
        b0 = (w / n_win) * (smax - sigma) / sigma  # §5.3 stressed-volatility component
        crit = smin + a * (smax - smin)
        tol = 1e-9 * smax
        if sigma <= crit + tol or smax - crit <= tol:   # no observed vol range -> full buffer
            b1 = bmax
        else:
            b1 = bmax * (1 - (sigma - crit) / (smax - crit))
        b = max(b0, b1)
        smp_rel = sigma * math.sqrt(l_days) * big_r * (1 + b)
        rows.append((t, n, sigma, big_r, b0, b1, b, smp_rel))
    return pd.DataFrame(rows, columns=["trade_date", "n_obs", "sigma", "R", "b0", "b1", "b",
                                       "smp_rel"])


def scan_range_per_lot(price: float, smp_rel: float, hours: int, round_to: int = 2) -> float:
    """Units: EUR/MWh price * relative SMP -> EUR/MWh (rounded as ECC does) * hours = EUR/lot."""
    return round(price * smp_rel, round_to) * hours


# --- 2. Portfolio SPAN -------------------------------------------------------------------

@dataclass
class SpanResult:
    scan_risk: float
    intra_charge: float
    spread_credit: float

    @property
    def im(self) -> float:
        return self.scan_risk + self.intra_charge - self.spread_credit


def tier_scan_risk(lots: float, scan_per_lot: float) -> float:
    """Worst weighted scenario loss of a net futures position (§4.1.3)."""
    losses = [-lots * move * scan_per_lot * wgt for move, wgt in SCAN_POINTS]
    return max(0.0, max(losses))


def intra_commodity_charge(net_long: float, net_short: float, charge_per_spread: float) -> float:
    """§4.1.4.2: number of spreads formed inside a multi-expiry tier times the charge."""
    return min(abs(net_long), abs(net_short)) * charge_per_spread


def intra_charge_rate(smp_tier_avg: float, smp_i: float, smp_j: float, rho: float) -> float:
    """§4.1.4.2: pi(Mi, Mj) = 2 * SMP_tier * NM / CM."""
    cm = smp_i + smp_j
    nm = cm - 2 * rho * min(smp_i, smp_j)
    return 2 * smp_tier_avg * nm / cm


def span_im(lots: dict[str, float], scan_per_lot: dict[str, float],
            credits: dict[tuple[str, str], float], commodity_of: dict[str, str] | None = None,
            mcap: float = 0.8, max_credit: float = 0.99) -> SpanResult:
    """SPAN IM of a futures portfolio.

    lots: product_id -> signed lots (1 lot = 1 MW over the delivery period)
    credits: unordered pair of product_ids -> credit rate C_P (from ECC's spread file)
    Credits are granted for opposite positions only, pairs in descending credit order; each
    spread consumes min(remaining risk A, remaining risk B) from both legs and earns
    C_P * 2 * min(...)  - i.e. IM = M_x + M_y - 2 * IC * min(M_x, M_y) (ECC Guide p. 14),
    which equals SPAN spread formation with ECC's risk-weighted leg ratios.
    """
    commodity_of = commodity_of or {}
    risk = {p: tier_scan_risk(q, scan_per_lot[p]) for p, q in lots.items() if q != 0}
    remaining = dict(risk)
    pairs = []
    for (a, b), c in credits.items():
        if a in remaining and b in remaining and lots[a] * lots[b] < 0:
            if commodity_of.get(a, "power") != commodity_of.get(b, "power"):
                c = min(c, mcap)                   # ESMA Art. 27 cap between different products
            pairs.append((min(c, max_credit), a, b))
    credit_total = 0.0
    for c, a, b in sorted(pairs, reverse=True):
        used = min(remaining[a], remaining[b])
        if used <= 0:
            continue
        credit_total += c * 2 * used
        remaining[a] -= used
        remaining[b] -= used
    return SpanResult(scan_risk=sum(risk.values()), intra_charge=0.0, spread_credit=credit_total)
