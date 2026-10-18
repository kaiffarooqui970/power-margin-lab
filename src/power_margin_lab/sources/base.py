"""PriceSource interface: everything the margin models need from market data.

Models only ever see a *tenor series* frame with the columns

    trade_date, tenor, product_id, price [EUR/MWh], ret_1d, delivery_hours, price_source

so a source can be swapped (REAL ECC SPAN-file settlements, the SMARD PROXY, later EEX/LSEG
history) without touching src/margin or src/validation. `price_source` is carried into every
result row.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..model.tenors import build_tenor_series

TENOR_COLUMNS = ["trade_date", "tenor", "product_id", "price", "ret_1d", "delivery_hours",
                 "price_source"]


class PriceSource(ABC):
    name: str
    kind: str  # "REAL" | "PROXY"

    @abstractmethod
    def tenor_series(self, tenors: list[str]) -> pd.DataFrame: ...


class ContractPriceSource(PriceSource):
    """A source with contract-level settlement prices (REAL data). Tenor mapping and the
    no-roll return rule are applied centrally in model.tenors.build_tenor_series."""

    @abstractmethod
    def settlements(self) -> pd.DataFrame:
        """Columns: trade_date (date), product_id (e.g. DEBM-2026-11), price (EUR/MWh)."""

    def tenor_series(self, tenors: list[str]) -> pd.DataFrame:
        return build_tenor_series(self.settlements(), tenors, self.kind)
