"""Stage `margin`: SPAN-hist parameters, and IM per portfolio for every model.

Two result sets, both in fct_margin_result:
- "today" (as_of = latest REAL date): exposures from REAL settlement prices; SPAN-current uses
  ECC's real scanning ranges and credits; FHS/SP use PROXY scenario history
  (price_source=REAL, scenario_source=PROXY).
- history: every PROXY business day with enough history (price_source=scenario_source=PROXY).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .. import warehouse as wh
from ..config import Paths, load_portfolios
from ..margin import fhs, span
from ..margin.aggregate import liquidity_addon, market_risk_im
from ..margin.stress import stress_window
from ..model.portfolios import Portfolio, portfolios_from_config
from ..model.products import Product

RESULT_COLUMNS = ["as_of_date", "run", "portfolio_id", "model", "component", "value_eur",
                  "price_source", "scenario_source", "window_flag", "window_obs", "binding"]


@dataclass
class Panel:
    """PROXY tenor series as aligned arrays (dates x tenors)."""

    dates: list[date]
    tenors: list[str]
    r: np.ndarray
    price: np.ndarray
    hours: np.ndarray
    product: np.ndarray


def make_panel(ts: pd.DataFrame, tenors: list[str]) -> Panel:
    piv = {c: ts.pivot(index="trade_date", columns="tenor", values=c)[tenors]
           for c in ("ret_1d", "price", "delivery_hours", "product_id")}
    dates = [pd.Timestamp(d).date() for d in piv["price"].index]
    return Panel(dates, tenors, piv["ret_1d"].to_numpy(float), piv["price"].to_numpy(float),
                 piv["delivery_hours"].to_numpy(float), piv["product_id"].to_numpy(object))


def _minus_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - years, day=28)


def fhs_window(panel: Panel, t: int, years: int, mpor: int) -> tuple[np.ndarray, bool]:
    lo = _minus_years(panel.dates[t], years)
    idx = np.array([s for s in range(mpor, t + 1) if panel.dates[s] > lo], dtype=int)
    return idx, panel.dates[0] <= lo


def var_es_matrix(losses: np.ndarray, q: float, es_q: float) -> tuple[np.ndarray, np.ndarray]:
    var = np.quantile(losses, q, axis=0, method="inverted_cdf")
    thr = np.quantile(losses, es_q, axis=0, method="inverted_cdf")
    es = np.array([losses[losses[:, j] >= thr[j], j].mean() for j in range(losses.shape[1])])
    return np.maximum(var, 0.0), np.maximum(es, 0.0)


def all_books(portfolios: list[Portfolio]) -> list[Portfolio]:
    """Portfolios plus their single legs (needed for diversification ratios)."""
    books = list(portfolios)
    for p in portfolios:
        if len(p.positions) > 1:
            books.extend(p.legs())
    return books


def exposure_matrix(books: list[Portfolio], tenors: list[str], price: np.ndarray,
                    hours: np.ndarray) -> np.ndarray:
    """K x B matrix: signed MW * delivery hours * price per tenor and book."""
    e = np.zeros((len(tenors), len(books)))
    for b, book in enumerate(books):
        for tenor, mw in book.positions.items():
            k = tenors.index(tenor)
            e[k, b] = mw * hours[k] * price[k]
    return e


class CreditBook:
    """ECC inter-commodity credits of one file date, plus tenor-pair lookup for SPAN-hist."""

    def __init__(self, credits: pd.DataFrame, tenor_products_now: dict[str, str]):
        self.c = {}
        for r in credits.itertuples(index=False):
            self.c[(r.product_id_a, r.product_id_b)] = r.credit
            self.c[(r.product_id_b, r.product_id_a)] = r.credit
        self.tp = tenor_products_now

    def get(self, a: str, b: str) -> float:
        return self.c.get((a, b), 0.0)

    def by_products(self, prods: list[str]) -> dict[tuple[str, str], float]:
        return {(a, b): self.get(a, b) for i, a in enumerate(prods) for b in prods[i + 1:]}

    def hist(self, ta: str, tb: str, pa: Product, pb: Product) -> float:
        """SPAN-hist credit for tenors (ta, tb) mapped to (pa, pb) on a historical date
        (D-034): the latest ECC credit of the same tenor pair, or - if the two contracts
        overlap (month inside quarter etc.) - the latest credit of the analogous overlapping
        pair (first sub-period inside the containing tenor's current contract)."""
        if not (pa.contains(pb) or pb.contains(pa)):
            return self.get(self.tp[ta], self.tp[tb])
        big_t, small = (ta, pb) if pa.contains(pb) else (tb, pa)
        big_now = Product.from_id(self.tp[big_t])
        subs = big_now.months() if small.delivery_type == "M" else [
            Product(m.delivery_start, "Q") for m in big_now.months()[::3]]
        return self.get(subs[0].product_id, big_now.product_id)


def run(paths: Paths, cfg: dict) -> dict:
    con = wh.connect(paths.warehouse)
    tenors = cfg["tenors"]
    fc, sc, spc = cfg["fhs"], cfg["stress"], cfg["span"]
    mpor = fc["mpor_days"]
    ts = wh.read(con, "fct_tenor_series")
    ts["trade_date"] = pd.to_datetime(ts["trade_date"]).dt.date
    as_of = pd.Timestamp(wh.read(con, "meta_run")["as_of_date"].iloc[0]).date()
    portfolios = portfolios_from_config(load_portfolios(paths))
    books = all_books(portfolios)

    proxy = make_panel(ts[ts["price_source"] == "PROXY"], tenors)
    real_now = ts[(ts["price_source"] == "REAL") & (ts["trade_date"] == as_of)].set_index("tenor")
    scans = wh.read(con, "fct_span_parameter")
    scans["as_of_date"] = pd.to_datetime(scans["as_of_date"]).dt.date
    scans_now = scans[(scans["as_of_date"] == as_of) & (scans["model"] == "ECC")].set_index(
        "product_id")["scan_eur_per_lot"].to_dict()
    credits = wh.read(con, "fct_spread_credit")
    credits["as_of_date"] = pd.to_datetime(credits["as_of_date"]).dt.date
    dates = [d for d in credits["as_of_date"] if d <= as_of]
    if not dates:
        raise RuntimeError("no ECC intercommodityspreads file on or before the as-of date; run "
                           "`python -m power_margin_lab.ingest.ecc_files --with-spreads`")
    credit_date = max(dates)
    cb = CreditBook(credits[credits["as_of_date"] == credit_date],
                    real_now["product_id"].to_dict())

    # --- SPAN-hist parameters on PROXY ------------------------------------------------------
    smp = {}
    detail = []
    for k, tenor in enumerate(tenors):
        d = span.smp_series(proxy.dates, proxy.r[:, k], spc)
        smp[tenor] = d["smp_rel"].to_numpy()
        d.insert(1, "tenor", tenor)
        d["product_id"] = proxy.product[:, k]
        d["price"] = proxy.price[:, k]
        d["delivery_hours"] = proxy.hours[:, k]
        detail.append(d)
    detail = pd.concat(detail, ignore_index=True)
    detail["scan_eur_per_mwh"] = (detail["price"] * detail["smp_rel"]).round(
        spc["round_eur_per_mwh"])
    detail["scan_eur_per_lot"] = detail["scan_eur_per_mwh"] * detail["delivery_hours"]
    detail["price_source"] = "PROXY"
    wh.write(con, "fct_span_hist_detail", detail)
    hist_params = pd.DataFrame({
        "as_of_date": detail["trade_date"], "valid_date": None,
        "product_id": detail["product_id"], "model": "SPAN-hist",
        "scan_eur_per_lot": detail["scan_eur_per_lot"],
        "scan_eur_per_mwh": detail["scan_eur_per_mwh"], "price_source": "PROXY"}).dropna(
        subset=["scan_eur_per_lot"])
    wh.write(con, "fct_span_parameter",
             pd.concat([scans[scans["model"] == "ECC"], hist_params], ignore_index=True))

    sig = {fc["ewma_lambda"]: fhs.ewma_sigma(proxy.r, fc["ewma_lambda"], fc["ewma_seed_obs"]),
           fc["ewma_lambda_sensitivity"]: fhs.ewma_sigma(proxy.r, fc["ewma_lambda_sensitivity"],
                                                         fc["ewma_seed_obs"])}
    lam_label = {fc["ewma_lambda"]: "FHS", fc["ewma_lambda_sensitivity"]: "FHS-l097"}
    rows: list[tuple] = []

    def risk_models(t: int, expo: np.ndarray, run_name: str, psrc: str, d: date) -> None:
        """FHS (both lambdas), SP and MRIM for all books at panel index t."""
        window, full = fhs_window(proxy, t, fc["lookback_years"], mpor)
        if len(window) < fc["min_window_obs"]:
            return
        flag = "full" if full else "short"
        fhs_main = None
        for lam, s in sig.items():
            scen = fhs.filtered_scenarios(proxy.r, s, t, window, mpor, fc["vol_floor_quantile"])
            var, es = var_es_matrix(fhs.portfolio_losses(scen.returns, expo),
                                    fc["confidence"], fc["es_confidence"])
            for b, book in enumerate(books):
                rows.append((d, run_name, book.portfolio_id, lam_label[lam], "var", var[b], psrc,
                             "PROXY", flag, len(scen.returns), None))
                rows.append((d, run_name, book.portfolio_id, lam_label[lam], "es", es[b], psrc,
                             "PROXY", flag, len(scen.returns), None))
            if lam == fc["ewma_lambda"]:
                fhs_main = var
        sidx = stress_window(proxy.dates, t, sc["start"], sc["end"])
        sp = np.full(len(books), np.nan)
        if len(sidx) >= sc["min_obs"]:
            sscen = fhs.unfiltered_scenarios(proxy.r, sidx, mpor)
            if len(sscen.returns) >= sc["min_obs"]:
                sp = np.maximum(np.quantile(fhs.portfolio_losses(sscen.returns, expo),
                                            sc["confidence"], axis=0, method="inverted_cdf"), 0)
        for b, book in enumerate(books):
            if np.isfinite(sp[b]):
                rows.append((d, run_name, book.portfolio_id, "SP", "var", sp[b], psrc, "PROXY",
                             flag, len(sidx), None))
            im, binding = market_risk_im(float(fhs_main[b]), float(sp[b]))
            gross = float(np.sum(np.abs(expo[:, b])))
            im += liquidity_addon(gross, cfg["liquidity_addon"])
            rows.append((d, run_name, book.portfolio_id, "MRIM", "im", im, psrc, "PROXY", flag,
                         len(window), binding))

    def span_rows(d: date, run_name: str, model: str, psrc: str, prods: dict[str, str],
                  scan: dict[str, float], credit_fn) -> None:
        for book in books:
            lots, ok = {}, True
            for tenor, mw in book.positions.items():
                p = prods[tenor]
                if p not in scan or not np.isfinite(scan[p]):
                    ok = False
                    break
                lots[p] = lots.get(p, 0.0) + mw
            if not ok:
                continue
            res = span.span_im(lots, scan, credit_fn(book), mcap=spc["mcap_cross_commodity"],
                               max_credit=spc["max_credit"])
            for comp, v in (("scan_risk", res.scan_risk), ("spread_credit", res.spread_credit),
                            ("im", res.im)):
                rows.append((d, run_name, book.portfolio_id, model, comp, v, psrc, None, None,
                             None, None))

    # --- today: REAL prices -------------------------------------------------------------
    t_now = proxy.dates.index(as_of)
    price_now = np.array([real_now.loc[k, "price"] for k in tenors])
    hours_now = np.array([real_now.loc[k, "delivery_hours"] for k in tenors], dtype=float)
    prods_now = real_now["product_id"].to_dict()
    risk_models(t_now, exposure_matrix(books, tenors, price_now, hours_now), "today", "REAL", as_of)

    def credit_by_products(prods):
        return lambda book: cb.by_products(sorted({prods[t] for t in book.positions}))

    span_rows(as_of, "today", "SPAN-current", "REAL", prods_now, scans_now,
              credit_by_products(prods_now))

    # Variant (today only, D-029): current volatility from REAL futures returns (EWMA over the
    # collected SPAN-file history), historical shocks from the proxy.
    real_r = ts[ts["price_source"] == "REAL"].pivot(index="trade_date", columns="tenor",
                                                   values="ret_1d")[tenors].to_numpy(float)
    lam = fc["ewma_lambda"]
    seed = min(fc["ewma_seed_obs"], int(np.min(np.sum(np.isfinite(real_r), axis=0))))
    real_sig_now = fhs.ewma_sigma(real_r, lam, seed)[-1]
    window, full = fhs_window(proxy, t_now, fc["lookback_years"], mpor)
    expo_now = exposure_matrix(books, tenors, price_now, hours_now)
    scen = fhs.filtered_scenarios(proxy.r, sig[lam], t_now, window, mpor,
                                  fc["vol_floor_quantile"], sig_t_override=real_sig_now)
    var_rv, es_rv = var_es_matrix(fhs.portfolio_losses(scen.returns, expo_now), fc["confidence"],
                                  fc["es_confidence"])
    sp_now = {r[2]: r[5] for r in rows if r[1] == "today" and r[3] == "SP"}
    for b, book in enumerate(books):
        flag = "full" if full else "short"
        rows.append((as_of, "today", book.portfolio_id, "FHS-realvol", "var", var_rv[b], "REAL",
                     "PROXY", flag, len(scen.returns), None))
        rows.append((as_of, "today", book.portfolio_id, "FHS-realvol", "es", es_rv[b], "REAL",
                     "PROXY", flag, len(scen.returns), None))
        im, binding = market_risk_im(float(var_rv[b]), sp_now.get(book.portfolio_id))
        rows.append((as_of, "today", book.portfolio_id, "MRIM-realvol", "im", im, "REAL",
                     "PROXY", flag, len(window), binding))
    scan_hist_now = {prods_now[k]: span.scan_range_per_lot(
        price_now[i], smp[k][t_now], int(hours_now[i]), spc["round_eur_per_mwh"])
        for i, k in enumerate(tenors)}
    span_rows(as_of, "today", "SPAN-hist", "REAL", prods_now, scan_hist_now,
              credit_by_products(prods_now))

    # --- history: PROXY -------------------------------------------------------------------
    for t in range(len(proxy.dates)):
        d = proxy.dates[t]
        risk_models(t, exposure_matrix(books, tenors, proxy.price[t], proxy.hours[t]),
                    "history", "PROXY", d)
        prods = {k: proxy.product[t, i] for i, k in enumerate(tenors)}
        scan = {prods[k]: span.scan_range_per_lot(proxy.price[t, i], smp[k][t],
                                                  int(proxy.hours[t, i]), spc["round_eur_per_mwh"])
                for i, k in enumerate(tenors) if np.isfinite(smp[k][t])}

        def credit_hist(book, prods=prods):
            ts_ = list(book.positions)
            return {(prods[a], prods[b]): cb.hist(a, b, Product.from_id(prods[a]),
                                                   Product.from_id(prods[b]))
                    for i, a in enumerate(ts_) for b in ts_[i + 1:]}

        span_rows(d, "history", "SPAN-hist", "PROXY", prods, scan, credit_hist)

    res = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    wh.write(con, "fct_margin_result", res)
    wh.write(con, "meta_margin", pd.DataFrame([{"as_of_date": as_of,
                                                "credit_file_date": credit_date}]))
    out = {"rows": len(res), "credit_file_date": str(credit_date),
           "history_days": int(res[res["run"] == "history"]["as_of_date"].nunique())}
    con.close()
    return out
