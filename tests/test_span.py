import math

import numpy as np
import pytest

from power_margin_lab.margin import span


def test_scan_risk_single_position():
    # 20 MW DEBM Nov-26: 28.12 EUR/MWh x 720 h = 20,246.40 EUR per lot
    assert span.tier_scan_risk(20, 20246.40) == pytest.approx(404928.0)
    assert span.tier_scan_risk(-20, 20246.40) == pytest.approx(404928.0)
    assert span.tier_scan_risk(0, 20246.40) == 0.0


def test_extreme_scenario_weight_does_not_bind_for_futures():
    # +-300 % x 0.33 = 0.99 x range < 1.0 x range
    assert span.tier_scan_risk(1, 100.0) == pytest.approx(100.0)


def test_units_scan_per_lot():
    assert span.scan_range_per_lot(191.49, 28.12 / 191.49, 720) == pytest.approx(20246.40)
    assert span.scan_range_per_lot(100.0, 0.123456, 743) == pytest.approx(12.35 * 743)


def test_ecc_guide_example_inter_commodity_spread():
    """ECC 'A Guide to Margining' (Sep 2026) p. 14: DEBM +5 vs G3BM -5, IC 0.66 -> 30,870.05."""
    res = span.span_im({"DEBM": 5, "G3BM": -5}, {"DEBM": 6919.20, "G3BM": 2328.72},
                       {("DEBM", "G3BM"): 0.66}, commodity_of={"DEBM": "power", "G3BM": "gas"})
    assert res.im == pytest.approx(30870.05, abs=0.01)


def test_calendar_spread_credit():
    res = span.span_im({"Y1": 50, "Y2": -50}, {"Y1": 126319.20, "Y2": 46906.56},
                       {("Y1", "Y2"): 0.73})
    assert res.scan_risk == pytest.approx(50 * 126319.20 + 50 * 46906.56)
    assert res.spread_credit == pytest.approx(0.73 * 2 * 50 * 46906.56)


def test_no_credit_for_same_direction_and_cross_commodity_cap():
    same = span.span_im({"A": 10, "B": 5}, {"A": 100.0, "B": 100.0}, {("A", "B"): 0.9})
    assert same.spread_credit == 0.0
    capped = span.span_im({"A": 10, "B": -10}, {"A": 100.0, "B": 100.0}, {("A", "B"): 0.95},
                          commodity_of={"A": "power", "B": "gas"}, mcap=0.8)
    assert capped.spread_credit == pytest.approx(0.8 * 2 * 1000)


def test_intra_commodity_charge():
    # rho = 1 and equal SMPs: no basis risk -> no charge; rho = 0: charge 2 x tier SMP
    assert span.intra_charge_rate(10.0, 10.0, 10.0, 1.0) == pytest.approx(0.0)
    assert span.intra_charge_rate(10.0, 10.0, 10.0, 0.0) == pytest.approx(20.0)
    assert span.intra_commodity_charge(30, -20, 5.0) == pytest.approx(100.0)


CFG = {"ewma_lambda": 0.99, "lookback_returns": 255, "alpha_r": 0.99, "r_min": 2.66,
       "r_max": 3.5, "stress_weight_w": 5, "buffer_a": 0.2, "buffer_max": 0.25,
       "liquidation_days": 2, "min_obs_for_r": 100}


def test_smp_constant_vol():
    r = np.tile([0.01, -0.01], 150)
    d = span.smp_series(list(range(300)), r, CFG).iloc[-1]
    assert d["sigma"] == pytest.approx(0.01)
    assert d["R"] == pytest.approx(2.66)        # |z| = 1 -> floored at R_min
    assert d["b"] == pytest.approx(0.25)        # sigma at sigma_min -> full 25 % buffer
    assert d["smp_rel"] == pytest.approx(0.01 * math.sqrt(2) * 2.66 * 1.25)


def test_smp_short_history_uses_r_max_and_skips_zero_returns():
    r = np.array([0.0] * 10 + [0.01, -0.01] * 30)
    d = span.smp_series(list(range(len(r))), r, CFG).iloc[-1]
    assert d["n_obs"] == 60 and d["R"] == 3.5


def test_smp_buffer_after_stress():
    calm, stress = [0.005, -0.005] * 150, [0.05, -0.05] * 150
    d = span.smp_series(list(range(600)), np.array(stress + calm), CFG).iloc[-1]
    assert d["b0"] > 0 and d["b"] == pytest.approx(max(d["b0"], d["b1"]))
