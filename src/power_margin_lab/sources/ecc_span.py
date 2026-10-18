"""REAL source: settlement prices of DEBM/DEBQ/DEBY from the daily ECC SPAN files.

History is only as long as the SPAN files collected locally (ECC publishes ~1 month; the daily
download job extends it). Settlement prices come from EEX via ECC's SPAN file and are used for
local analysis only; they are never written to the repository.
"""

from __future__ import annotations

import pandas as pd

from .base import ContractPriceSource


class EccSpanFileSource(ContractPriceSource):
    name = "ecc_span_file"
    kind = "REAL"

    def __init__(self, fct_settlement: pd.DataFrame):
        self._s = fct_settlement[fct_settlement["price_source"] == "REAL"][
            ["trade_date", "product_id", "price"]].copy()

    def settlements(self) -> pd.DataFrame:
        return self._s
