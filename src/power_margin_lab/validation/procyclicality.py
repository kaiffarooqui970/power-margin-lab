"""Procyclicality metrics of an IM time series (all in observation = business-day steps)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def max_increase(im: pd.Series, horizon: int) -> float:
    """Largest relative IM increase over `horizon` business days."""
    s = im.dropna()
    s = s[s > 0]
    if len(s) <= horizon:
        return float("nan")
    return float(np.nanmax(s.to_numpy()[horizon:] / s.to_numpy()[:-horizon] - 1.0))


def peak_to_trough(im: pd.Series) -> float:
    s = im.dropna()
    s = s[s > 0]
    return float(s.max() / s.min()) if len(s) else float("nan")


def window_stats(im: pd.Series, start: date, end: date, base: date) -> dict:
    """IM on `base` and the peak within [start, end] as a multiple of it."""
    s = im.dropna()
    w = s[(s.index >= start) & (s.index <= end)]
    b = s[s.index <= base]
    if w.empty or b.empty or b.iloc[-1] <= 0:
        return {"base_im": float("nan"), "peak_im": float("nan"), "peak_date": None,
                "peak_over_base": float("nan")}
    return {"base_im": float(b.iloc[-1]), "peak_im": float(w.max()),
            "peak_date": w.idxmax(), "peak_over_base": float(w.max() / b.iloc[-1])}


def summarise(im: pd.Series, cfg: dict) -> dict:
    out = {"peak_to_trough": peak_to_trough(im), "max_5d_increase": max_increase(im, 5),
           "max_30d_increase": max_increase(im, 30)}
    out.update({f"aug2022_{k}": v for k, v in window_stats(
        im, cfg["start"], cfg["end"], cfg["base"]).items()})
    return out
