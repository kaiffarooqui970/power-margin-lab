"""Prisma-inspired Filtered Historical Simulation (FHS).

Structure from ECC's public Prisma material (99 %, 2-day MPOR, 3-year window, joint historical
scenarios); every calibration detail below is an assumption of this project (DECISIONS D-020+):

- EWMA variance per risk factor: var_t = lam * var_{t-1} + (1 - lam) * r_t^2, seeded with the
  mean square of the first `seed_obs` returns. sigma_t is the estimate after observing r_t.
- Devolatised return z_s = r_s / sigma_{s-1}; filtered return r~_s = z_s * sigma_T.
- Volatility floor: both sigma_{s-1} and sigma_T are floored at the `floor_q` quantile of the
  tenor's sigma_{s-1} values used in the scenario window.
- 2-day scenario ending at s: (1 + r~_s)(1 + r~_{s-1}) - 1 (overlapping).
- All tenors use the same historical dates (joint scenarios), so correlations and therefore
  portfolio offsets come from history.
- P&L of a scenario = sum_k MW_k * hours_k * F_k(T) * r~2_{s,k}; VaR = empirical quantile of
  the losses (inverted CDF), ES = mean loss beyond the ES quantile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def ewma_sigma(r: np.ndarray, lam: float, seed_obs: int = 20) -> np.ndarray:
    """EWMA volatility per column; NaN returns carry the previous variance forward."""
    r = np.atleast_2d(np.asarray(r, dtype=float).T).T
    n, k = r.shape
    out = np.full((n, k), np.nan)
    for j in range(k):
        col = r[:, j]
        valid = np.flatnonzero(np.isfinite(col))
        if len(valid) < seed_obs:
            continue
        start = valid[seed_obs - 1]
        var = float(np.mean(col[valid[:seed_obs]] ** 2))
        out[start, j] = var
        for i in range(start + 1, n):
            if np.isfinite(col[i]):
                var = lam * var + (1 - lam) * col[i] ** 2
            out[i, j] = var
    return np.sqrt(out)


def empirical_quantile(x: np.ndarray, q: float) -> float:
    return float(np.quantile(x, q, method="inverted_cdf"))


def var_es(losses: np.ndarray, var_q: float, es_q: float) -> tuple[float, float]:
    losses = losses[np.isfinite(losses)]
    var = empirical_quantile(losses, var_q)
    tail = losses[losses >= empirical_quantile(losses, es_q)]
    return max(var, 0.0), max(float(tail.mean()), 0.0)


@dataclass
class ScenarioSet:
    returns: np.ndarray      # (n_scen, K) MPOR-day relative returns
    end_index: np.ndarray    # index of the last day of each scenario


def mpor_returns(daily: np.ndarray, end_idx: np.ndarray, mpor: int) -> np.ndarray:
    """Compounded `mpor`-day returns ending at each index in end_idx."""
    out = np.ones((len(end_idx), daily.shape[1]))
    for j in range(mpor):
        out *= 1.0 + daily[end_idx - j]
    return out - 1.0


def filtered_scenarios(r: np.ndarray, sigma: np.ndarray, t: int, window: np.ndarray,
                       mpor: int, floor_q: float,
                       sig_t_override: np.ndarray | None = None) -> ScenarioSet:
    """FHS scenarios for evaluation index t from scenario end indices `window` (all <= t).

    `sig_t_override` replaces the current volatility (used for the "real-vol" today variant,
    where sigma_T comes from REAL futures returns while the shocks come from the proxy)."""
    window = window[window - (mpor - 1) >= 1]   # every scenario day needs sigma of the day before
    days = np.unique(np.concatenate([window - j for j in range(mpor)]))
    # floor = quantile of the volatilities actually used for devolatising (q = 0: no floor)
    floor = np.nanquantile(sigma[days - 1], floor_q, axis=0)
    sig_t = np.maximum(sigma[t], floor) if sig_t_override is None else sig_t_override
    filt = np.full_like(r, np.nan)
    denom = np.maximum(sigma[days - 1], floor)
    filt[days] = r[days] / denom * sig_t
    scen = mpor_returns(filt, window, mpor)
    keep = np.all(np.isfinite(scen), axis=1)
    return ScenarioSet(scen[keep], window[keep])


def unfiltered_scenarios(r: np.ndarray, window: np.ndarray, mpor: int) -> ScenarioSet:
    window = window[window - (mpor - 1) >= 0]
    scen = mpor_returns(r, window, mpor)
    keep = np.all(np.isfinite(scen), axis=1)
    return ScenarioSet(scen[keep], window[keep])


def portfolio_losses(scen: np.ndarray, exposure: np.ndarray) -> np.ndarray:
    """exposure_k = signed MW * delivery hours * current price (EUR per unit relative return)."""
    return -(scen @ exposure)
