"""Market-risk IM = max(FHS, SP) (ECC Prisma webinar Jun 2026, p. 7) plus optional add-on."""

from __future__ import annotations

import math


def market_risk_im(fhs_var: float, sp_var: float | None) -> tuple[float, str]:
    """Returns (MRIM, binding component). SP missing (before the stress window) -> FHS."""
    if sp_var is None or (isinstance(sp_var, float) and math.isnan(sp_var)):
        return fhs_var, "FHS"
    return (sp_var, "SP") if sp_var > fhs_var else (fhs_var, "FHS")


def liquidity_addon(gross_notional: float, cfg: dict) -> float:
    """Simplification (D-027): rate x gross notional. Not ECC's market-level LA."""
    if not cfg.get("enabled", False):
        return 0.0
    return cfg["rate_of_gross_notional"] * gross_notional
