"""Stage `backtest`: backtests, procyclicality, diversification and validation checks."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import warehouse as wh
from ..config import Paths, load_portfolios
from ..margin import fhs
from ..model.portfolios import portfolios_from_config
from ..validation import backtest as bt
from ..validation import procyclicality as pc
from .margin_run import all_books, make_panel

BACKTEST_MODELS = {"SPAN-hist": "im", "FHS": "var", "FHS-l097": "var", "MRIM": "im"}
PROCYCLICALITY_MODELS = ["SPAN-hist", "FHS", "MRIM"]
TENOR_TO_ECC_MATURITY = {"M1": ("DEBM", 1), "M2": ("DEBM", 2), "M3": ("DEBM", 3),
                         "Q1": ("DEBQ", 1), "Q2": ("DEBQ", 2), "Y1": ("DEBY", 1),
                         "Y2": ("DEBY", 2)}


def realised_pnl(panel, books, tenors, mpor: int) -> pd.DataFrame:
    """P&L of each book held from t to t+mpor (positions fixed at t, constant maturity)."""
    rows = []
    n = len(panel.dates)
    for t in range(n - mpor):
        growth = np.prod(1.0 + panel.r[t + 1:t + 1 + mpor], axis=0) - 1.0
        for book in books:
            pnl = sum(mw * panel.hours[t, tenors.index(k)] * panel.price[t, tenors.index(k)]
                      * growth[tenors.index(k)] for k, mw in book.positions.items())
            rows.append((panel.dates[t], book.portfolio_id, pnl))
    return pd.DataFrame(rows, columns=["as_of_date", "portfolio_id", "pnl_2d"])


def fisher_ci(r: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n <= 3 or not np.isfinite(r) or abs(r) >= 1:
        return float("nan"), float("nan")
    f, se = math.atanh(r), 1 / math.sqrt(n - 3)
    return math.tanh(f - z * se), math.tanh(f + z * se)


def run(paths: Paths, cfg: dict) -> dict:
    con = wh.connect(paths.warehouse)
    tenors, mpor = cfg["tenors"], cfg["fhs"]["mpor_days"]
    p_exp = 1 - cfg["backtest"]["confidence"]
    win = cfg["backtest"]["traffic_light_window"]
    res = wh.read(con, "fct_margin_result")
    res["as_of_date"] = pd.to_datetime(res["as_of_date"]).dt.date
    ts = wh.read(con, "fct_tenor_series")
    ts["trade_date"] = pd.to_datetime(ts["trade_date"]).dt.date
    portfolios = portfolios_from_config(load_portfolios(paths))
    books = all_books(portfolios)
    panel = make_panel(ts[ts["price_source"] == "PROXY"], tenors)
    hist = res[res["run"] == "history"]

    # --- backtest (PROXY) ----------------------------------------------------------------
    pnl = realised_pnl(panel, books, tenors, mpor)
    full_dates = set(hist[(hist["model"] == "FHS") & (hist["window_flag"] == "full")]
                     ["as_of_date"])
    daily_rows, summary = [], []
    for model, comp in BACKTEST_MODELS.items():
        im = hist[(hist["model"] == model) & (hist["component"] == comp)][
            ["as_of_date", "portfolio_id", "value_eur"]]
        m = im.merge(pnl, on=["as_of_date", "portfolio_id"])
        m = m[m["as_of_date"].isin(full_dates)].sort_values("as_of_date")
        m["model"] = model
        m["loss_2d"] = -m["pnl_2d"]
        m["breach"] = m["loss_2d"] > m["value_eur"]
        daily_rows.append(m)
        for pid, g in m.groupby("portfolio_id"):
            s = bt.summarise(g["breach"].to_numpy(), p_exp, win)
            summary.append({"portfolio_id": pid, "model": model, "price_source": "PROXY",
                            "start": g["as_of_date"].min(), "end": g["as_of_date"].max(), **s})
    daily = pd.concat(daily_rows, ignore_index=True).rename(columns={"value_eur": "im"})
    daily["price_source"] = "PROXY"
    wh.write(con, "fct_backtest_daily", daily)
    wh.write(con, "fct_backtest_result", pd.DataFrame(summary))

    # --- procyclicality (PROXY, full-window period) ---------------------------------------
    pro = []
    for model in PROCYCLICALITY_MODELS:
        comp = BACKTEST_MODELS[model]
        for p in portfolios:
            s = hist[(hist["model"] == model) & (hist["component"] == comp)
                     & (hist["portfolio_id"] == p.portfolio_id)
                     & hist["as_of_date"].isin(full_dates)].set_index("as_of_date")["value_eur"]
            pro.append({"portfolio_id": p.portfolio_id, "model": model, "price_source": "PROXY",
                        **pc.summarise(s.sort_index(), cfg["procyclicality"])})
    wh.write(con, "fct_procyclicality", pd.DataFrame(pro))

    # --- diversification ------------------------------------------------------------------
    div = []
    for p in portfolios:
        if len(p.positions) < 2:
            continue
        legs = [leg.portfolio_id for leg in p.legs()]
        for run_name, models in (("today", ["SPAN-current", "SPAN-hist", "FHS", "MRIM"]),
                                 ("history", ["SPAN-hist", "FHS", "MRIM"])):
            sub = res[res["run"] == run_name]
            for model in models:
                comp = "var" if model == "FHS" else "im"
                x = sub[(sub["model"] == model) & (sub["component"] == comp)]
                if run_name == "history":
                    x = x[x["as_of_date"].isin(full_dates)]
                piv = x.pivot_table(index="as_of_date", columns="portfolio_id",
                                    values="value_eur")
                if p.portfolio_id not in piv or not all(leg in piv for leg in legs):
                    continue
                ratio = piv[p.portfolio_id] / piv[legs].sum(axis=1)
                div.append({"portfolio_id": p.portfolio_id, "run": run_name, "model": model,
                            "price_source": "REAL" if run_name == "today" else "PROXY",
                            "ratio_mean": ratio.mean(), "ratio_min": ratio.min(),
                            "ratio_max": ratio.max(), "n": len(ratio)})
    wh.write(con, "fct_diversification", pd.DataFrame(div))

    # --- SPAN-hist vs real ECC scanning ranges (22 REAL dates) ----------------------------
    real = ts[ts["price_source"] == "REAL"]
    scans = wh.read(con, "fct_span_parameter")
    scans["as_of_date"] = pd.to_datetime(scans["as_of_date"]).dt.date
    ecc = scans[scans["model"] == "ECC"][["as_of_date", "product_id", "scan_eur_per_lot"]]
    det = wh.read(con, "fct_span_hist_detail")
    det["trade_date"] = pd.to_datetime(det["trade_date"]).dt.date
    v = real.merge(det[["trade_date", "tenor", "smp_rel", "sigma", "R", "b"]],
                   on=["trade_date", "tenor"]).merge(
        ecc, left_on=["trade_date", "product_id"], right_on=["as_of_date", "product_id"])
    rnd = cfg["span"]["round_eur_per_mwh"]
    v["span_hist_eur_per_lot"] = (v["price"] * v["smp_rel"]).round(rnd) * v["delivery_hours"]
    v["error_pct"] = 100 * (v["span_hist_eur_per_lot"] / v["scan_eur_per_lot"] - 1)
    v["ecc_smp_rel"] = v["scan_eur_per_lot"] / v["delivery_hours"] / v["price"]
    wh.write(con, "fct_span_validation_daily", v[[
        "trade_date", "tenor", "product_id", "smp_rel", "ecc_smp_rel", "error_pct"]])
    val = v.groupby("tenor")["error_pct"].agg(
        mean_error_pct="mean", mean_abs_error_pct=lambda x: x.abs().mean(),
        max_abs_error_pct=lambda x: x.abs().max(), n="count").reindex(tenors).reset_index()
    wh.write(con, "fct_span_validation", val)

    # --- formula check on REAL short history + buffer comparison (as-of date) -------------
    as_of = max(real["trade_date"])
    buf = wh.read(con, "fct_ecc_margin_buffer")
    buf["as_of_date"] = pd.to_datetime(buf["as_of_date"]).dt.date
    buf_now = buf[buf["as_of_date"] == as_of].set_index(["ecc_code", "relative_maturity"])[
        "margin_buffer"]
    det_now = det[det["trade_date"] == as_of].set_index("tenor")
    chk = []
    for tenor in tenors:
        g = real[real["tenor"] == tenor].sort_values("trade_date")
        r = g["ret_1d"].dropna().to_numpy()
        lam = cfg["span"]["ewma_lambda"]
        w = lam ** np.arange(len(r), 0, -1)
        sig = math.sqrt(float(np.sum(w * r ** 2) / np.sum(w)))
        last = g.iloc[-1]
        sel = (ecc["as_of_date"] == as_of) & (ecc["product_id"] == last["product_id"])
        ecc_scan = float(ecc[sel]["scan_eur_per_lot"].iloc[0])
        b_ecc = float(buf_now.get(TENOR_TO_ECC_MATURITY[tenor], np.nan))
        implied_r = ecc_scan / last["delivery_hours"] / (
            last["price"] * sig * math.sqrt(cfg["span"]["liquidation_days"]) * (1 + b_ecc))
        chk.append({"tenor": tenor, "n_real_returns": len(r), "sigma_real_21d": sig,
                    "sigma_proxy": det_now.loc[tenor, "sigma"], "ecc_buffer": b_ecc,
                    "span_hist_buffer": det_now.loc[tenor, "b"],
                    "span_hist_R": det_now.loc[tenor, "R"],
                    "implied_R_real": implied_r,
                    "implied_R_in_range": bool(cfg["span"]["r_min"] <= implied_r
                                               <= cfg["span"]["r_max"])})
    wh.write(con, "fct_span_formula_check", pd.DataFrame(chk))

    # --- single-factor proxy: correlation check -------------------------------------------
    piv = real.pivot(index="trade_date", columns="tenor", values="ret_1d")
    piv_p = real.pivot(index="trade_date", columns="tenor", values="price").iloc[-1]
    hrs = real.pivot(index="trade_date", columns="tenor", values="delivery_hours").iloc[-1]
    corr_rows = []
    for p in portfolios:
        if len(p.positions) != 2 or np.prod(list(p.positions.values())) > 0:
            continue
        (ta, qa), (tb, qb) = p.positions.items()
        j = piv[[ta, tb]].dropna()
        rho = float(j[ta].corr(j[tb]))
        lo, hi = fisher_ci(rho, len(j))
        sa, sb = j[ta].std(), j[tb].std()
        ea, eb = qa * hrs[ta] * piv_p[ta] * sa, qb * hrs[tb] * piv_p[tb] * sb

        def sd(rh, ea=ea, eb=eb):
            return math.sqrt(max(ea ** 2 + eb ** 2 + 2 * rh * ea * eb, 0.0))

        corr_rows.append({"portfolio_id": p.portfolio_id, "pair": f"{ta}/{tb}", "n": len(j),
                          "rho_real": rho, "rho_ci_low": lo, "rho_ci_high": hi,
                          "rho_proxy": 1.0, "im_ratio_real_vs_rho1": sd(rho) / sd(1.0),
                          "im_ratio_ci_low_rho": sd(lo) / sd(1.0) if np.isfinite(lo) else np.nan,
                          "price_source": "REAL"})
    wh.write(con, "fct_correlation_check", pd.DataFrame(corr_rows))
    base_r = panel.r[:, tenors.index("M1")]
    br = pd.Series(base_r).dropna()
    m1_real = piv["M1"].dropna()
    wh.write(con, "fct_proxy_diagnostics", pd.DataFrame([{
        "proxy_lag1_autocorr": float(br.autocorr(1)),
        "real_m1_lag1_autocorr": float(m1_real.autocorr(1)),
        "real_m1_n": len(m1_real),
        "proxy_m1_daily_vol_last21": float(br.iloc[-21:].std()),
        "real_m1_daily_vol_last21": float(m1_real.std()),
        "proxy_m1_ewma_sigma_asof": float(fhs.ewma_sigma(panel.r[:, [0]], cfg["fhs"][
            "ewma_lambda"], cfg["fhs"]["ewma_seed_obs"])[-1, 0])}]))

    out = {"backtest_obs": int(daily.groupby(["model", "portfolio_id"]).size().max()),
           "breaches_total": int(daily["breach"].sum())}
    con.close()
    return out
