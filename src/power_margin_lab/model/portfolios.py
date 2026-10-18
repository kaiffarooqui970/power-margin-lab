"""Test portfolios defined on relative tenors."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .tenors import parse_tenor


@dataclass(frozen=True)
class Portfolio:
    portfolio_id: str
    name: str
    positions: dict[str, float]  # tenor -> signed MW

    def legs(self) -> list[Portfolio]:
        """Single-leg sub-portfolios, used for diversification ratios."""
        return [Portfolio(f"{self.portfolio_id}:{t}", f"{self.name} [{t}]", {t: mw})
                for t, mw in self.positions.items()]


def portfolios_from_config(cfg: dict) -> list[Portfolio]:
    out = []
    for pid, spec in cfg.items():
        pos = {str(t): float(mw) for t, mw in spec["positions"].items()}
        for t in pos:
            parse_tenor(t)
        out.append(Portfolio(pid, spec["name"], pos))
    return out


def dim_portfolio(portfolios: list[Portfolio]) -> pd.DataFrame:
    return pd.DataFrame([(p.portfolio_id, p.name) for p in portfolios],
                        columns=["portfolio_id", "name"])


def fct_position(portfolios: list[Portfolio]) -> pd.DataFrame:
    rows = [(p.portfolio_id, t, abs(mw), 1 if mw > 0 else -1, mw)
            for p in portfolios for t, mw in p.positions.items()]
    return pd.DataFrame(rows, columns=["portfolio_id", "tenor", "mw", "sign", "signed_mw"])
