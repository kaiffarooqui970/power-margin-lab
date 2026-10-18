import numpy as np
import pytest

from power_margin_lab.margin import fhs
from power_margin_lab.margin.aggregate import market_risk_im


def test_ewma_recursion():
    r = np.array([0.01, -0.02, 0.03, 0.0, -0.01])
    s = fhs.ewma_sigma(r, 0.94, seed_obs=2)
    var = np.mean(r[:2] ** 2)
    assert np.isnan(s[0, 0]) and s[1, 0] == pytest.approx(np.sqrt(var))
    for i in range(2, 5):
        var = 0.94 * var + 0.06 * r[i] ** 2
        assert s[i, 0] == pytest.approx(np.sqrt(var))


def test_ewma_skips_missing():
    r = np.array([0.01, 0.01, np.nan, 0.02])
    s = fhs.ewma_sigma(r, 0.9, seed_obs=2)
    assert s[2, 0] == pytest.approx(s[1, 0])


def test_var_es_hand_computed():
    losses = np.arange(1.0, 101.0)
    var, es = fhs.var_es(losses, 0.99, 0.975)
    assert var == 99.0                 # 99th order statistic (inverted CDF)
    assert es == pytest.approx(99.0)   # mean of {98, 99, 100}


def test_fhs_tiny_example_hand_computed():
    """Constant vol: filtering is the identity. 1-day MPOR, one tenor, 1 MW x 10 h x 100 EUR."""
    r = np.array([[0.0], [0.05], [-0.10], [0.02], [-0.04], [0.01]])
    sigma = np.full_like(r, 0.05)
    window = np.arange(1, 6)
    scen = fhs.filtered_scenarios(r, sigma, t=5, window=window, mpor=1, floor_q=0.0)
    losses = fhs.portfolio_losses(scen.returns, np.array([1 * 10 * 100.0]))
    assert sorted(losses) == pytest.approx([-50.0, -20.0, -10.0, 40.0, 100.0])
    assert fhs.empirical_quantile(losses, 0.8) == pytest.approx(40.0)


def test_filtering_rescales_to_current_vol():
    r = np.array([[0.0], [0.02], [0.02], [0.04]])
    sigma = np.array([[0.01], [0.02], [0.02], [0.04]])
    scen = fhs.filtered_scenarios(r, sigma, t=3, window=np.array([1, 2, 3]), mpor=1,
                                  floor_q=0.0)
    # z = r_s / sigma_{s-1} = [0.02/0.01, 0.02/0.02, 0.04/0.02] = [2, 1, 2]; x sigma_T = 0.04
    assert scen.returns[:, 0] == pytest.approx([0.08, 0.04, 0.08])


def test_vol_floor_bounds_devolatised_returns():
    r = np.array([[0.0], [0.03], [0.01], [0.01]])
    sigma = np.array([[1e-6], [0.01], [0.01], [0.01]])   # near-zero vol before day 1
    no_floor = fhs.filtered_scenarios(r, sigma, 3, np.array([1, 2, 3]), 1, 0.0)
    floored = fhs.filtered_scenarios(r, sigma, 3, np.array([1, 2, 3]), 1, 0.5)
    assert abs(no_floor.returns).max() > 100
    assert abs(floored.returns).max() < 1


def test_two_day_compounding():
    daily = np.array([[0.0], [0.10], [-0.05]])
    assert fhs.mpor_returns(daily, np.array([2]), 2)[0, 0] == pytest.approx(1.10 * 0.95 - 1)


def test_joint_scenarios_offset_perfect_spread():
    rng = np.random.default_rng(1)
    base = rng.normal(0, 0.02, 300)
    r = np.column_stack([base, base])                  # two perfectly correlated tenors
    sigma = fhs.ewma_sigma(r, 0.94, 20)
    window = np.arange(30, 300)
    scen = fhs.filtered_scenarios(r, sigma, 299, window, 2, 0.05)
    spread = np.array([1e6, -1e6])
    leg = np.array([1e6, 0.0])
    var_spread, _ = fhs.var_es(fhs.portfolio_losses(scen.returns, spread), 0.99, 0.975)
    var_leg, _ = fhs.var_es(fhs.portfolio_losses(scen.returns, leg), 0.99, 0.975)
    assert var_leg > 0 and var_spread == pytest.approx(0.0, abs=1e-6)


def test_market_risk_im_max():
    assert market_risk_im(10.0, 12.0) == (12.0, "SP")
    assert market_risk_im(10.0, 8.0) == (10.0, "FHS")
    assert market_risk_im(10.0, float("nan")) == (10.0, "FHS")
