"""Stage `build`: domain data model (dim_product, fct_settlement, fct_tenor_series, ...)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from .. import warehouse as wh
from ..config import Paths, load_portfolios
from ..model.portfolios import dim_portfolio, fct_position, portfolios_from_config
from ..model.products import ECC_CODE, Product, last_trading_day
from ..sources.ecc_span import EccSpanFileSource
from ..sources.smard_proxy import SmardProxySource

GERMAN_BASE = tuple(ECC_CODE.values())


def _to_date(x) -> date:
    return pd.Timestamp(x).date()


def settlements_from_span(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """raw_ecc_span_settlement -> fct_settlement rows + per-row consistency checks."""
    rows, checks = [], []
    for r in raw.itertuples(index=False):
        if _to_date(r.calc_date) > _to_date(r.settlement_date):
            continue  # listed after its last trading day (cascaded); not a tradable price
        p = Product.from_ecc(r.pf_code, int(r.period[:4]), int(r.period[4:]))
        rows.append((_to_date(r.calc_date), p.product_id, float(r.price), "REAL",
                     r.source_file))
        checks.append((p.product_id, _to_date(r.calc_date),
                       _to_date(r.delivery_first) == p.delivery_start,
                       _to_date(r.delivery_last) == p.delivery_end,
                       int(round(r.contract_hours)), p.delivery_hours,
                       _to_date(r.settlement_date)))
    fct = pd.DataFrame(rows, columns=["trade_date", "product_id", "price", "price_source",
                                      "source_file"])
    chk = pd.DataFrame(checks, columns=["product_id", "calc_date", "start_ok", "end_ok",
                                        "ecc_contract_hours", "delivery_hours",
                                        "ecc_last_trading_day"])
    return fct, chk


def ecc_scan_ranges(raw: pd.DataFrame) -> pd.DataFrame:
    de = raw[raw["product_code"].isin(GERMAN_BASE)].copy()
    prods = [Product.from_ecc(c, y, m) for c, y, m in
             zip(de["product_code"], de["expiry_year"], de["expiry_month"], strict=True)]
    de["product_id"] = [p.product_id for p in prods]
    de["delivery_hours"] = [p.delivery_hours for p in prods]
    return pd.DataFrame({
        "as_of_date": pd.to_datetime(de["calc_date"]).dt.date,
        "valid_date": pd.to_datetime(de["valid_date"]).dt.date,
        "product_id": de["product_id"], "model": "ECC",
        "scan_eur_per_lot": de["price_scan_range"],
        "scan_eur_per_mwh": de["price_scan_range"] / de["delivery_hours"],
        "price_source": "REAL"}).reset_index(drop=True)


def ecc_spread_credits(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["as_of_date", "product_id_a", "product_id_b", "ratio_a",
                                     "ratio_b", "credit"])
    pa = [Product.from_ecc(c, y, m).product_id for c, y, m in
          zip(raw["cc_a"], raw["expiry_year_a"], raw["expiry_month_a"], strict=True)]
    pb = [Product.from_ecc(c, y, m).product_id for c, y, m in
          zip(raw["cc_b"], raw["expiry_year_b"], raw["expiry_month_b"], strict=True)]
    return pd.DataFrame({"as_of_date": pd.to_datetime(raw["calc_date"]).dt.date,
                         "spread_id": raw["spread_id"], "product_id_a": pa, "product_id_b": pb,
                         "ratio_a": raw["ratio_a"], "ratio_b": raw["ratio_b"],
                         "credit": raw["credit"]})


def ecc_margin_buffer(raw: pd.DataFrame) -> pd.DataFrame:
    s = raw["product_maturity"].str.split("_", expand=True)
    df = pd.DataFrame({"as_of_date": pd.to_datetime(raw["calc_date"]).dt.date,
                       "ecc_code": s[0], "relative_maturity": s[1].astype(int),
                       "margin_buffer": raw["margin_buffer"]})
    return df[df["ecc_code"].isin(GERMAN_BASE)].reset_index(drop=True)


def dim_product(product_ids: set[str], checks: pd.DataFrame) -> pd.DataFrame:
    last = checks.sort_values("calc_date").groupby("product_id").last()
    rows = []
    for pid in sorted(product_ids):
        p = Product.from_id(pid)
        ecc_h = last["ecc_contract_hours"].get(pid)
        rows.append((pid, p.ecc_code, "base", p.delivery_type, p.delivery_start,
                     p.delivery_end, p.delivery_hours,
                     None if ecc_h is None else int(ecc_h),
                     last["ecc_last_trading_day"].get(pid), last_trading_day(p)))
    return pd.DataFrame(rows, columns=[
        "product_id", "ecc_code", "load_type", "delivery_type", "delivery_start",
        "delivery_end", "delivery_hours", "ecc_contract_hours", "ecc_last_trading_day",
        "rule_last_trading_day"])


def anchor_frame(real_ts: pd.DataFrame, scans: pd.DataFrame, t: date) -> pd.DataFrame:
    a = real_ts[real_ts["trade_date"] == t][["tenor", "product_id", "price"]]
    s = scans[scans["as_of_date"] == t][["product_id", "scan_eur_per_mwh"]]
    out = a.merge(s, on="product_id", how="left")
    if out["scan_eur_per_mwh"].isna().any():
        raise ValueError(f"missing ECC scanning range for anchor products on {t}")
    return out


def run(paths: Paths, cfg: dict) -> dict:
    con = wh.connect(paths.warehouse)
    tenors = cfg["tenors"]

    fct_settlement, checks = settlements_from_span(wh.read(con, "raw_ecc_span_settlement"))
    scans = ecc_scan_ranges(wh.read(con, "raw_ecc_scanning_range"))
    credits = ecc_spread_credits(wh.read(con, "raw_ecc_spread_credit"))
    buffers = ecc_margin_buffer(wh.read(con, "raw_ecc_margin_buffer"))

    real = EccSpanFileSource(fct_settlement).tenor_series(tenors)
    as_of = max(real["trade_date"])
    daily = wh.read(con, "int_smard_daily_base")
    proxy_src = SmardProxySource(daily, anchor_frame(real, scans, as_of), as_of,
                                 cfg["proxy"]["smoothing_days"], end=as_of)
    proxy = proxy_src.tenor_series(tenors)
    tenor_series = pd.concat([real, proxy], ignore_index=True)

    pids = set(fct_settlement["product_id"]) | set(scans["product_id"]) | set(
        tenor_series["product_id"])
    portfolios = portfolios_from_config(load_portfolios(paths))

    wh.write(con, "dim_product", dim_product(pids, checks))
    wh.write(con, "dq_span_product_checks", checks)
    wh.write(con, "fct_settlement", fct_settlement)
    wh.write(con, "fct_tenor_series", tenor_series)
    wh.write(con, "fct_span_parameter", scans)
    wh.write(con, "fct_spread_credit", credits)
    wh.write(con, "fct_ecc_margin_buffer", buffers)
    wh.write(con, "dim_portfolio", dim_portfolio(portfolios))
    wh.write(con, "fct_position", fct_position(portfolios))
    wh.write(con, "meta_run", pd.DataFrame([{
        "as_of_date": as_of, "proxy_start": min(proxy["trade_date"]),
        "proxy_end": max(proxy["trade_date"]), "real_start": min(real["trade_date"]),
        "real_days": real["trade_date"].nunique(),
        "proxy_scales": ", ".join(f"{k}={v:.3f}" for k, v in proxy_src.scales.items())}]))
    out = {"as_of": str(as_of), "real_days": real["trade_date"].nunique(),
           "proxy_days": proxy["trade_date"].nunique(),
           "hours_mismatch": int((checks["ecc_contract_hours"] != checks["delivery_hours"]).sum()),
           "delivery_mismatch": int((~checks["start_ok"] | ~checks["end_ok"]).sum())}
    con.close()
    return out
