import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from power_margin_lab.validation import backtest as bt
from power_margin_lab.validation import procyclicality as pc


def test_kupiec_zero_breaches():
    lr, p = bt.kupiec_pof(250, 0, 0.01)
    assert lr == pytest.approx(-2 * 250 * math.log(0.99))
    assert p == pytest.approx(0.02497, abs=1e-4)


def test_kupiec_exact_rate():
    lr, p = bt.kupiec_pof(100, 1, 0.01)
    assert lr == pytest.approx(0.0, abs=1e-12) and p == pytest.approx(1.0)


def test_christoffersen_detects_clustering():
    clustered = np.array([0] * 240 + [1] * 10)
    spread = np.zeros(250, dtype=int)
    spread[::25] = 1
    assert bt.christoffersen_independence(clustered)[1] < 0.001
    assert bt.christoffersen_independence(spread)[1] > 0.1


def test_christoffersen_hand_computed():
    h = np.array([0, 1, 1, 0, 0, 0, 1, 0])
    # n00=2 n01=2 n10=2 n11=1 ; pi=3/7 pi01=1/2 pi11=1/3
    ll0 = 4 * math.log(4 / 7) + 3 * math.log(3 / 7)
    ll1 = 2 * math.log(0.5) + 2 * math.log(0.5) + 2 * math.log(2 / 3) + math.log(1 / 3)
    assert bt.christoffersen_independence(h)[0] == pytest.approx(-2 * (ll0 - ll1))


@pytest.mark.parametrize("n,zone", [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"),
                                    (10, "red"), (15, "red")])
def test_traffic_light(n, zone):
    assert bt.traffic_light(n) == zone


def test_rolling_breach_max():
    h = np.zeros(600, dtype=int)
    h[100:106] = 1
    h[500] = 1
    assert bt.rolling_breach_max(h, 250) == 6


def test_procyclicality_metrics():
    idx = [date(2022, 6, 1 + i) for i in range(10)]
    s = pd.Series([100, 100, 100, 100, 100, 200, 200, 200, 200, 50.0], index=idx)
    assert pc.peak_to_trough(s) == 4.0
    assert pc.max_increase(s, 5) == pytest.approx(1.0)
    w = pc.window_stats(s, date(2022, 6, 3), date(2022, 6, 9), date(2022, 6, 2))
    assert w["peak_over_base"] == 2.0
