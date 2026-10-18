"""LATER: EEX / LSEG settlement-price history (access requested, not yet available).

To plug it in (see README, "Echte EEX-Historie anschließen"):
1. Export daily settlement prices for German Power Base Month/Quarter/Year futures to
   data/raw/eex/ (never commit them).
2. Implement `settlements()` below: return trade_date, product_id (model.products.Product
   ids such as DEBM-2026-11, DEBQ-2027-Q1, DEBY-2027) and price in EUR/MWh. Add a schema
   contract in contracts/schemas/ and validate before returning.
3. Set `history.source: eex` in config/model.yml. Tenor mapping, the no-roll return rule, FHS,
   SPAN-hist and the backtest all run unchanged and results are labelled REAL.
"""

from __future__ import annotations

import pandas as pd

from .base import ContractPriceSource


class EexHistorySource(ContractPriceSource):
    name = "eex_history"
    kind = "REAL"

    def __init__(self, raw_dir):
        self.raw_dir = raw_dir

    def settlements(self) -> pd.DataFrame:
        raise NotImplementedError(
            "EEX/LSEG history is not connected yet. See src/power_margin_lab/sources/eex.py "
            "and README section 'Echte EEX-Historie anschließen'.")
