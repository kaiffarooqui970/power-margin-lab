from datetime import date, datetime

import pandas as pd
import pytest

from power_margin_lab.model.products import (
    BERLIN,
    Product,
    _easter,
    delivery_hours,
    is_business_day,
    last_trading_day,
)
from power_margin_lab.model.tenors import build_tenor_series, map_tenor


@pytest.mark.parametrize("pid,hours", [
    ("DEBM-2027-03", 743),   # DST starts: one hour less
    ("DEBM-2026-10", 745),   # DST ends: one hour more
    ("DEBM-2026-11", 720), ("DEBM-2027-02", 672), ("DEBM-2028-02", 696),
    ("DEBQ-2027-Q1", 2159), ("DEBQ-2026-Q4", 2209), ("DEBQ-2027-Q2", 2184),
    ("DEBY-2027", 8760), ("DEBY-2028", 8784),
])
def test_delivery_hours_dst(pid, hours):
    assert Product.from_id(pid).delivery_hours == hours


def test_wall_clock_subtraction_pitfall():
    """Documents the trap: same-ZoneInfo subtraction ignores DST; delivery_hours must not."""
    naive = (datetime(2026, 11, 1, tzinfo=BERLIN) - datetime(2026, 10, 1, tzinfo=BERLIN))
    assert naive.total_seconds() / 3600 == 744
    assert delivery_hours(date(2026, 10, 1), date(2026, 10, 31)) == 745


def test_daylight_saving_days():
    assert delivery_hours(date(2027, 3, 28), date(2027, 3, 28)) == 23
    assert delivery_hours(date(2026, 10, 25), date(2026, 10, 25)) == 25


def test_product_ids_roundtrip_and_ecc_mapping():
    for pid in ("DEBM-2026-11", "DEBQ-2027-Q3", "DEBY-2030"):
        assert Product.from_id(pid).product_id == pid
    assert Product.from_ecc("DEBQ", 2027, 1).product_id == "DEBQ-2027-Q1"
    assert Product.from_ecc("DEBY", 2027, 1).delivery_end == date(2027, 12, 31)
    with pytest.raises(ValueError):
        Product(date(2027, 2, 1), "Q")


def test_contains():
    q1 = Product.from_id("DEBQ-2027-Q1")
    assert q1.contains(Product.from_id("DEBM-2027-01"))
    assert not q1.contains(Product.from_id("DEBM-2027-04"))
    assert Product.from_id("DEBY-2027").contains(q1)


def test_calendar():
    assert _easter(2027) == date(2027, 3, 28)
    assert not is_business_day(date(2027, 3, 26))       # Good Friday
    assert not is_business_day(date(2026, 12, 25))
    assert is_business_day(date(2026, 12, 31))


# Last trading days observed in ECC_SPANFILE_20261016 (setlDate); contract calendar facts.
OBSERVED_EXPIRY = {
    "DEBQ-2027-Q1": date(2026, 12, 29), "DEBQ-2027-Q2": date(2027, 3, 25),
    "DEBQ-2027-Q3": date(2027, 6, 28), "DEBQ-2027-Q4": date(2027, 9, 28),
    "DEBQ-2028-Q1": date(2027, 12, 29), "DEBQ-2028-Q2": date(2028, 3, 29),
    "DEBQ-2028-Q3": date(2028, 6, 28), "DEBQ-2028-Q4": date(2028, 9, 27),
    "DEBQ-2029-Q1": date(2028, 12, 27), "DEBQ-2029-Q2": date(2029, 3, 27),
    "DEBQ-2029-Q3": date(2029, 6, 27), "DEBY-2027": date(2026, 12, 29),
    "DEBY-2028": date(2027, 12, 29), "DEBY-2030": date(2029, 12, 27),
    "DEBY-2032": date(2031, 12, 29), "DEBY-2034": date(2033, 12, 28),
}


@pytest.mark.parametrize("pid,expected", OBSERVED_EXPIRY.items())
def test_expiry_rule_matches_observed(pid, expected):
    assert last_trading_day(Product.from_id(pid)) == expected


def test_map_tenor_calendar():
    t = date(2026, 10, 16)
    got = {k: map_tenor(t, k).product_id for k in ("M1", "M3", "Q1", "Q2", "Y1", "Y2")}
    assert got == {"M1": "DEBM-2026-11", "M3": "DEBM-2027-01", "Q1": "DEBQ-2027-Q1",
                   "Q2": "DEBQ-2027-Q2", "Y1": "DEBY-2027", "Y2": "DEBY-2028"}


def test_map_tenor_after_quarter_and_year_expiry():
    t = date(2026, 12, 30)              # Q1-27 and Cal-27 expired on 29 Dec
    assert map_tenor(t, "M1").product_id == "DEBM-2027-01"
    assert map_tenor(t, "Q1").product_id == "DEBQ-2027-Q2"
    assert map_tenor(t, "Y1").product_id == "DEBY-2028"


def test_map_tenor_with_listing_excludes_delivery():
    t = date(2026, 10, 16)
    listed = {"DEBM-2026-10", "DEBM-2026-12"}       # Oct is in delivery, Nov not listed
    assert map_tenor(t, "M1", listed).product_id == "DEBM-2026-12"


def test_no_roll_returns():
    """M1 rolls from Oct to Nov on 1 Oct: the return must be Nov(t)/Nov(t-1), never Nov/Oct."""
    s = pd.DataFrame([
        (date(2026, 9, 29), "DEBM-2026-10", 100.0), (date(2026, 9, 29), "DEBM-2026-11", 200.0),
        (date(2026, 9, 30), "DEBM-2026-10", 101.0), (date(2026, 9, 30), "DEBM-2026-11", 202.0),
        (date(2026, 10, 1), "DEBM-2026-10", 99.0), (date(2026, 10, 1), "DEBM-2026-11", 204.02),
        (date(2026, 10, 1), "DEBM-2026-12", 300.0),
        (date(2026, 10, 2), "DEBM-2026-11", 210.0), (date(2026, 10, 2), "DEBM-2026-12", 303.0),
    ], columns=["trade_date", "product_id", "price"])
    ts = build_tenor_series(s, ["M1", "M2"], "REAL").set_index(["trade_date", "tenor"])
    assert ts.loc[(date(2026, 9, 30), "M1"), "product_id"] == "DEBM-2026-10"
    assert ts.loc[(date(2026, 10, 1), "M1"), "product_id"] == "DEBM-2026-11"
    assert ts.loc[(date(2026, 10, 1), "M1"), "ret_1d"] == pytest.approx(0.01)
    # M2 on 1 Oct is Dec, which had no price on 30 Sep -> missing, not a cross-contract return
    assert pd.isna(ts.loc[(date(2026, 10, 1), "M2"), "ret_1d"])
    assert ts.loc[(date(2026, 10, 2), "M2"), "ret_1d"] == pytest.approx(0.01)
