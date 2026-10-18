"""Build reports/margin_comparison.md + figures from warehouse tables.

Every number in the report and in the README result blocks is read from pipeline output here;
nothing is typed by hand. Every table carries its price source (REAL / PROXY).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .. import warehouse as wh  # noqa: E402

# Reference palette (dataviz skill, light mode); validated: 3 slots pass, aqua needs relief
# (every chart is accompanied by a table).
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", \
    "#fcfcfb"
SERIES = {"SPAN-hist": "#2a78d6", "MRIM": "#eb6834", "FHS": "#1baf7a"}
MAIN = ["P1", "P2", "P3", "P4", "P5"]
BANNER_DE = ("v1: historische Analyse nutzt einen SMARD-Proxy; echte EEX-Futures-Historie "
             "steht noch aus.")
BANNER_EN = "v1: historical analysis uses a SMARD proxy; real EEX futures history pending."


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=8, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _eur_m(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x / 1e6:,.2f}"


def _pct(x: float, digits: int = 1) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.{digits}f} %"


def _p(x: float) -> str:
    return "n/a" if pd.isna(x) else ("<0.001" if x < 0.001 else f"{x:.3f}")


def _d(x) -> str:
    return str(pd.Timestamp(x).date())


def _rng(s: pd.Series) -> str:
    lo, hi = int(s.min()), int(s.max())
    return f"{lo}" if lo == hi else f"{lo}-{hi}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


class Data:
    def __init__(self, con):
        r = wh.read(con, "fct_margin_result")
        r["as_of_date"] = pd.to_datetime(r["as_of_date"])
        self.res = r
        self.meta = wh.read(con, "meta_run").iloc[0]
        self.meta_margin = wh.read(con, "meta_margin").iloc[0]
        self.bt = wh.read(con, "fct_backtest_result")
        self.btd = wh.read(con, "fct_backtest_daily")
        self.btd["as_of_date"] = pd.to_datetime(self.btd["as_of_date"])
        self.pro = wh.read(con, "fct_procyclicality")
        self.div = wh.read(con, "fct_diversification")
        self.val = wh.read(con, "fct_span_validation")
        self.vald = wh.read(con, "fct_span_validation_daily")
        self.chk = wh.read(con, "fct_span_formula_check")
        self.corr = wh.read(con, "fct_correlation_check")
        self.diag = wh.read(con, "fct_proxy_diagnostics").iloc[0]
        self.quar = wh.read(con, "quarantine")
        self.drift = wh.read(con, "meta_schema_drift")
        self.ports = wh.read(con, "dim_portfolio").set_index("portfolio_id")["name"]

    def today(self, model: str, comp: str) -> pd.Series:
        x = self.res[(self.res["run"] == "today") & (self.res["model"] == model)
                     & (self.res["component"] == comp)]
        return x.set_index("portfolio_id")["value_eur"]

    def today_binding(self, model: str) -> pd.Series:
        x = self.res[(self.res["run"] == "today") & (self.res["model"] == model)
                     & (self.res["component"] == "im")]
        return x.set_index("portfolio_id")["binding"]


# --- sections ---------------------------------------------------------------------------

def today_table(d: Data) -> tuple[str, pd.DataFrame]:
    span_c, span_h = d.today("SPAN-current", "im"), d.today("SPAN-hist", "im")
    fhs_v, sp, mrim = d.today("FHS", "var"), d.today("SP", "var"), d.today("MRIM", "im")
    mrim_rv, b, b_rv = d.today("MRIM-realvol", "im"), d.today_binding("MRIM"), \
        d.today_binding("MRIM-realvol")
    t = pd.DataFrame({
        "Portfolio": [f"{p} {d.ports[p]}" for p in MAIN],
        "SPAN-current [EUR m]": [_eur_m(span_c[p]) for p in MAIN],
        "SPAN-hist [EUR m]": [_eur_m(span_h[p]) for p in MAIN],
        "FHS 99 % [EUR m]": [_eur_m(fhs_v[p]) for p in MAIN],
        "SP [EUR m]": [_eur_m(sp.get(p)) for p in MAIN],
        "MRIM = max(FHS, SP) [EUR m]": [_eur_m(mrim[p]) for p in MAIN],
        "binding": [b[p] for p in MAIN],
        "MRIM vs SPAN-current": [_pct(100 * (mrim[p] / span_c[p] - 1)) for p in MAIN],
        "MRIM real-vol [EUR m]": [_eur_m(mrim_rv[p]) for p in MAIN],
        "binding (real-vol)": [b_rv[p] for p in MAIN],
        "real-vol vs SPAN-current": [_pct(100 * (mrim_rv[p] / span_c[p] - 1)) for p in MAIN],
    })
    num = pd.DataFrame({"mrim_vs_span": [100 * (mrim[p] / span_c[p] - 1) for p in MAIN],
                        "rv_vs_span": [100 * (mrim_rv[p] / span_c[p] - 1) for p in MAIN],
                        "binding": [b[p] for p in MAIN], "binding_rv": [b_rv[p] for p in MAIN]},
                       index=MAIN)
    return md_table(t), num


def backtest_table(d: Data) -> str:
    b = d.bt[d.bt["portfolio_id"].isin(MAIN)].copy()
    b["model"] = pd.Categorical(b["model"], ["SPAN-hist", "FHS", "FHS-l097", "MRIM"])
    b = b.sort_values(["model", "portfolio_id"])
    t = pd.DataFrame({
        "Model": b["model"].astype(str), "Portfolio": b["portfolio_id"],
        "n": b["n_obs"], "breaches": b["breaches"], "expected": b["expected"].round(1),
        "Kupiec p": b["kupiec_p"].map(_p), "Christoffersen p": b["christoffersen_p"].map(_p),
        "Kupiec p (non-overl.)": b["kupiec_p_nonoverlap"].map(_p),
        "Christoffersen p (non-overl.)": b["christoffersen_p_nonoverlap"].map(_p),
        "last 250: breaches / zone": b["breaches_last_250"].astype(str) + " / "
        + b["zone_last_250"],
        "worst 250: breaches / zone": b["max_breaches_any_250"].astype(str) + " / "
        + b["zone_worst_250"], "source": b["price_source"]})
    return md_table(t)


def procyclicality_table(d: Data) -> str:
    p = d.pro.copy()
    p["model"] = pd.Categorical(p["model"], ["SPAN-hist", "FHS", "MRIM"])
    p = p.sort_values(["model", "portfolio_id"])
    t = pd.DataFrame({
        "Model": p["model"].astype(str), "Portfolio": p["portfolio_id"],
        "peak / trough": p["peak_to_trough"].map(lambda x: f"{x:.1f}x"),
        "max 5-day increase": p["max_5d_increase"].map(lambda x: _pct(100 * x, 0)),
        "max 30-day increase": p["max_30d_increase"].map(lambda x: _pct(100 * x, 0)),
        "IM 1 Jul 2022 [EUR m]": p["aug2022_base_im"].map(_eur_m),
        "peak Jul-Sep 2022 [EUR m]": p["aug2022_peak_im"].map(_eur_m),
        "peak date": pd.to_datetime(p["aug2022_peak_date"]).dt.strftime("%Y-%m-%d"),
        "peak / 1 Jul": p["aug2022_peak_over_base"].map(lambda x: f"{x:.2f}x"),
        "source": p["price_source"]})
    return md_table(t)


def diversification_table(d: Data) -> str:
    v = d.div[d.div["portfolio_id"].isin(["P3", "P4"])].copy()
    t = pd.DataFrame({
        "Portfolio": v["portfolio_id"], "run": v["run"], "Model": v["model"],
        "IM(portfolio) / sum IM(legs)": v.apply(
            lambda r: f"{r.ratio_mean:.2f}" if r.n == 1 else
            f"{r.ratio_mean:.2f} (min {r.ratio_min:.2f}, max {r.ratio_max:.2f}, n={r.n})",
            axis=1),
        "source": v["price_source"] + (v["run"] == "today").map(
            {True: " prices / PROXY scenarios", False: ""}).where(
            v["model"].isin(["FHS", "MRIM"]), "")})
    return md_table(t)


def validation_tables(d: Data) -> tuple[str, str]:
    v = d.val
    t1 = pd.DataFrame({"Tenor": v["tenor"], "days": v["n"],
                       "mean error": v["mean_error_pct"].map(_pct),
                       "mean abs error": v["mean_abs_error_pct"].map(lambda x: f"{x:.1f} %"),
                       "max abs error": v["max_abs_error_pct"].map(lambda x: f"{x:.1f} %"),
                       "source": "SPAN-hist on PROXY vs ECC (REAL)"})
    c = d.chk
    t2 = pd.DataFrame({
        "Tenor": c["tenor"], "REAL returns": c["n_real_returns"],
        "sigma REAL (daily)": c["sigma_real_21d"].map(lambda x: f"{100 * x:.2f} %"),
        "sigma PROXY (daily)": c["sigma_proxy"].map(lambda x: f"{100 * x:.2f} %"),
        "ECC buffer": c["ecc_buffer"].map(lambda x: f"{100 * x:.1f} %"),
        "SPAN-hist buffer": c["span_hist_buffer"].map(lambda x: f"{100 * x:.1f} %"),
        "SPAN-hist R": c["span_hist_R"].map(lambda x: f"{x:.2f}"),
        "implied R (REAL sigma, ECC buffer)": c["implied_R_real"].map(lambda x: f"{x:.2f}"),
        "inside [R_min, R_max]": c["implied_R_in_range"].map({True: "yes", False: "no"})})
    return md_table(t1), md_table(t2)


def correlation_table(d: Data) -> str:
    c = d.corr
    t = pd.DataFrame({
        "Portfolio": c["portfolio_id"], "pair": c["pair"], "n (REAL days)": c["n"],
        "rho REAL": c["rho_real"].map(lambda x: f"{x:.3f}"),
        "95 % CI": c.apply(lambda r: f"[{r.rho_ci_low:.3f}, {r.rho_ci_high:.3f}]", axis=1),
        "rho PROXY": "1 (by construction)",
        "parametric IM: REAL rho / rho=1": c["im_ratio_real_vs_rho1"].map(lambda x: f"{x:.2f}x"),
        "same, at lower CI bound": c["im_ratio_ci_low_rho"].map(lambda x: f"{x:.2f}x")})
    return md_table(t)


# --- figures ----------------------------------------------------------------------------

def fig_timeseries(d: Data, out: Path) -> None:
    fig, axes = plt.subplots(5, 1, figsize=(10, 12), sharex=True)
    fig.patch.set_facecolor(SURFACE)
    for ax, p in zip(axes, MAIN, strict=True):
        _style(ax)
        sub = d.btd[d.btd["portfolio_id"] == p]
        loss = sub[sub["model"] == "MRIM"].set_index("as_of_date")["loss_2d"].clip(lower=0)
        ax.plot(loss.index, loss / 1e6, color=MUTED, linewidth=0.6, label="realised 2-day loss")
        for model, marker in (("SPAN-hist", "v"), ("MRIM", "o")):
            s = sub[sub["model"] == model].set_index("as_of_date")
            ax.plot(s.index, s["im"] / 1e6, color=SERIES[model], linewidth=1.6, label=model)
            br = s[s["breach"]]
            ax.scatter(br.index, br["loss_2d"] / 1e6, marker=marker, s=34, color=SERIES[model],
                       edgecolor=SURFACE, linewidth=1.2, zorder=5, label=f"{model} breach")
        ax.set_title(f"{p} {d.ports[p]}", loc="left", fontsize=9, color=INK)
        ax.set_ylabel("EUR m", fontsize=8, color=INK2)
    axes[0].legend(loc="upper right", fontsize=7, frameon=False, ncol=5, labelcolor=INK2)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.suptitle("Initial margin vs realised 2-day loss, PROXY history (full 3-year window)",
                 x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def fig_2022(d: Data, out: Path, cfg: dict) -> None:
    lo, hi = pd.Timestamp("2022-05-01"), pd.Timestamp("2022-12-31")
    base = pd.Timestamp(cfg["procyclicality"]["base"])
    fig, axes = plt.subplots(1, 5, figsize=(13, 3.2), sharey=True)
    fig.patch.set_facecolor(SURFACE)
    h = d.res[(d.res["run"] == "history") & d.res["portfolio_id"].isin(MAIN)]
    for ax, p in zip(axes, MAIN, strict=True):
        _style(ax)
        for model, comp in (("SPAN-hist", "im"), ("FHS", "var"), ("MRIM", "im")):
            s = h[(h["portfolio_id"] == p) & (h["model"] == model) & (h["component"] == comp)
                  ].set_index("as_of_date")["value_eur"].sort_index()
            s = s[(s.index >= lo) & (s.index <= hi)]
            ax.plot(s.index, s / s[s.index <= base].iloc[-1], color=SERIES[model],
                    linewidth=1.6, label=model)
        ax.axhline(1, color=AXIS, linewidth=0.8)
        ax.set_title(p, loc="left", fontsize=9, color=INK)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[6, 8, 10, 12]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    axes[0].set_ylabel("IM / IM on 1 Jul 2022", fontsize=8, color=INK2)
    axes[-1].legend(fontsize=7, frameon=False, labelcolor=INK2)
    fig.suptitle("IM around the August 2022 price peak, indexed to 1 Jul 2022 (PROXY)", x=0.01,
                 ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def fig_span_validation(d: Data, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.2))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    v = d.vald.copy()
    v["trade_date"] = pd.to_datetime(v["trade_date"])
    for tenor, col in (("M1", SERIES["SPAN-hist"]), ("Q1", SERIES["MRIM"]),
                       ("Y1", SERIES["FHS"])):
        s = v[v["tenor"] == tenor].set_index("trade_date")["error_pct"]
        ax.plot(s.index, s, color=col, linewidth=1.6, marker="o", markersize=4, label=tenor)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    ax.set_ylabel("SPAN-hist / ECC - 1 [%]", fontsize=8, color=INK2)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(fontsize=7, frameon=False, labelcolor=INK2, loc="upper right", ncol=3)
    ax.set_title("SPAN-hist (formula on PROXY) vs ECC scanning ranges (REAL), per day",
                 loc="left", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=130, facecolor=SURFACE)
    plt.close(fig)


# --- interpretation (generated from the numbers) ----------------------------------------

def interpretation(d: Data, today: pd.DataFrame) -> tuple[list[str], list[str]]:
    n_sp = int((today["binding"] == "SP").sum())
    lo, hi = today["mrim_vs_span"].min(), today["mrim_vs_span"].max()
    m1 = d.val.set_index("tenor").loc["M1"]
    bt = d.bt[d.bt["portfolio_id"].isin(MAIN)].set_index(["model", "portfolio_id"])
    fhs_b = bt.loc["FHS"]["breaches"]
    mrim_b = bt.loc["MRIM"]["breaches"]
    exp = float(bt.loc["FHS"]["expected"].iloc[0])
    mrim_bt = bt.loc["MRIM"]
    mrim_rej = int(((mrim_bt["kupiec_p"] < 0.05) & (mrim_bt["breaches"] < exp)).sum())
    chk = d.chk.set_index("tenor")
    n_in = int(chk["implied_R_in_range"].sum())
    s_real, s_proxy = chk.loc["M1", "sigma_real_21d"], chk.loc["M1", "sigma_proxy"]
    pro = d.pro.set_index(["model", "portfolio_id"])["peak_to_trough"]
    p3 = d.div[(d.div["portfolio_id"] == "P3") & (d.div["run"] == "today")].set_index("model")[
        "ratio_mean"]
    c3 = d.corr.set_index("portfolio_id").loc["P3"]
    de = [
        f"Heute (REAL-Preise) liegt die marktrisikobasierte IM = max(FHS, SP) zwischen "
        f"{lo:+.0f} % und {hi:+.0f} % gegenüber SPAN mit den echten ECC-Parametern; in {n_sp} "
        f"von 5 Portfolios bindet die Stressperioden-Komponente.",
        f"Die SPAN-Formel von ECC, auf den SMARD-Proxy angewendet, unterschätzt die echten "
        f"Scanning Ranges für M1 im Mittel um {abs(m1['mean_error_pct']):.0f} %. Das passt zur "
        f"niedrigeren Proxy-Volatilität (M1 täglich {100 * s_proxy:.2f} % statt "
        f"{100 * s_real:.2f} % real); mit realer Volatilität läge der implizite "
        f"Risikomultiplikator für {n_in} von 7 Tenoren in ECCs Band [2,66; 3,5].",
        f"Im Rückvergleich auf Proxy-Historie hat die reine FHS {_rng(fhs_b)} "
        f"Überschreitungen bei {exp:.1f} erwarteten; max(FHS, SP) hat {_rng(mrim_b)} und ist "
        f"damit konservativ (Kupiec verwirft in {mrim_rej} von 5 Portfolios wegen zu weniger "
        f"Überschreitungen).",
        f"Die SP-Untergrenze dämpft die Prozyklizität: das Verhältnis Höchst- zu Tiefstwert "
        f"sinkt für P5 von {pro[('FHS', 'P5')]:.1f}x (FHS) auf {pro[('MRIM', 'P5')]:.1f}x.",
        f"Beim Kalenderspread P3 rechnet FHS heute mit {p3['FHS']:.2f} der Summe der "
        f"Einzel-IMs, SPAN mit {p3['SPAN-current']:.2f} - allerdings ist der Proxy "
        f"perfekt korreliert.",
        f"Mit der beobachteten Korrelation von {c3['rho_real']:.2f} (21 REAL-Tage) wäre die "
        f"parametrische IM von P3 {c3['im_ratio_real_vs_rho1']:.2f}x so hoch wie bei "
        f"Korrelation 1; die Spread-Entlastung der FHS ist also überzeichnet.",
        "Belastbare Aussagen zur Historie erfordern echte EEX-Futures-Daten; bis dahin sind "
        "die Backtest-Ergebnisse eine Methodenprüfung, keine Modellvalidierung.",
    ]
    en = [
        f"Today (REAL prices) market-risk IM = max(FHS, SP) is between {lo:+.0f} % and "
        f"{hi:+.0f} % relative to SPAN with ECC's real parameters; the stress-period component "
        f"binds for {n_sp} of 5 portfolios.",
        f"ECC's SPAN formula applied to the SMARD proxy underestimates the real M1 scanning "
        f"ranges by {abs(m1['mean_error_pct']):.0f} % on average. This is consistent with the "
        f"proxy's lower volatility (M1 daily {100 * s_proxy:.2f} % vs. {100 * s_real:.2f} % "
        f"real); with real volatility the implied risk multiplier lies in ECC's band "
        f"[2.66, 3.5] for {n_in} of 7 tenors.",
        f"In the backtest on proxy history, pure FHS has {_rng(fhs_b)} breaches against "
        f"{exp:.1f} expected; max(FHS, SP) has {_rng(mrim_b)} and is conservative (Kupiec "
        f"rejects because of too few breaches for {mrim_rej} of 5 portfolios).",
        f"The SP floor dampens procyclicality: the peak-to-trough ratio for P5 falls from "
        f"{pro[('FHS', 'P5')]:.1f}x (FHS) to {pro[('MRIM', 'P5')]:.1f}x.",
        f"For the calendar spread P3, FHS today charges {p3['FHS']:.2f} of the sum of leg IMs, "
        f"SPAN {p3['SPAN-current']:.2f} - but the proxy is perfectly correlated.",
        f"With the observed correlation of {c3['rho_real']:.2f} (21 REAL days) the parametric "
        f"IM of P3 would be {c3['im_ratio_real_vs_rho1']:.2f}x the correlation-1 value, so the "
        f"FHS spread offset is overstated.",
        "Firm conclusions about history need real EEX futures data; until then the backtest "
        "is a check of the method, not a validation of the model.",
    ]
    return de, en


def readme_block(d: Data, today: pd.DataFrame, lang: str) -> str:
    m1 = d.val.set_index("tenor").loc["M1"]
    bt = d.bt[d.bt["portfolio_id"].isin(MAIN)].set_index(["model", "portfolio_id"])
    c3 = d.corr.set_index("portfolio_id").loc["P3"]
    as_of = pd.Timestamp(d.meta["as_of_date"]).date()
    start, end = _d(bt.loc["FHS"]["start"].iloc[0]), _d(bt.loc["FHS"]["end"].iloc[0])
    if lang == "de":
        return "\n".join([
            f"*Automatisch erzeugt aus `reports/` (Stand {as_of}). Quelle je Zahl in Klammern.*",
            "",
            f"- Heute: max(FHS, SP) vs. SPAN-current: {today['mrim_vs_span'].min():+.0f} % bis "
            f"{today['mrim_vs_span'].max():+.0f} % je Portfolio; SP bindet in "
            f"{int((today['binding'] == 'SP').sum())}/5 (REAL-Preise, PROXY-Szenarien).",
            f"- SPAN-hist vs. echte ECC-Scanning-Ranges (M1, {int(m1['n'])} Tage): mittlerer "
            f"Fehler {m1['mean_error_pct']:+.1f} %, max. {m1['max_abs_error_pct']:.1f} % "
            f"(PROXY vs. REAL).",
            f"- Backtest {start} bis {end}: "
            f"FHS {_rng(bt.loc['FHS']['breaches'])}, "
            f"max(FHS, SP) {_rng(bt.loc['MRIM']['breaches'])}"
            f" Überschreitungen bei {bt.loc['FHS']['expected'].iloc[0]:.1f} erwarteten (PROXY).",
            f"- Korrelation Y1/Y2 real {c3['rho_real']:.2f} statt 1 im Proxy: mit realer "
            f"Korrelation wäre die IM des Kalenderspreads {c3['im_ratio_real_vs_rho1']:.2f}x so "
            f"hoch (parametrisch, REAL).",
            "", "Details: [reports/margin_comparison.md](reports/margin_comparison.md)"])
    return "\n".join([
        f"*Generated from `reports/` (as of {as_of}). Source of each number in brackets.*", "",
        f"- Today: max(FHS, SP) vs. SPAN-current: {today['mrim_vs_span'].min():+.0f} % to "
        f"{today['mrim_vs_span'].max():+.0f} % per portfolio; SP binds in "
        f"{int((today['binding'] == 'SP').sum())}/5 (REAL prices, PROXY scenarios).",
        f"- SPAN-hist vs. real ECC scanning ranges (M1, {int(m1['n'])} days): mean error "
        f"{m1['mean_error_pct']:+.1f} %, max {m1['max_abs_error_pct']:.1f} % (PROXY vs. REAL).",
        f"- Backtest {start} to {end}: FHS "
        f"{_rng(bt.loc['FHS']['breaches'])}, max(FHS, SP) "
        f"{_rng(bt.loc['MRIM']['breaches'])} breaches vs. "
        f"{bt.loc['FHS']['expected'].iloc[0]:.1f} expected (PROXY).",
        f"- Y1/Y2 correlation is {c3['rho_real']:.2f} in REAL data vs. 1 in the proxy: with the "
        f"real correlation the calendar-spread IM would be {c3['im_ratio_real_vs_rho1']:.2f}x "
        f"as high (parametric, REAL).",
        "", "Details: [reports/margin_comparison.md](reports/margin_comparison.md)"])


def update_readme(path: Path, block: str) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"<!-- RESULTS:START -->.*?<!-- RESULTS:END -->",
                 lambda m: f"<!-- RESULTS:START -->\n{block}\n<!-- RESULTS:END -->", text,
                 flags=re.S)
    path.write_text(new, encoding="utf-8")


def build(con, reports: Path, cfg: dict, readme_dir: Path | None) -> dict:
    d = Data(con)
    fig_dir = reports / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    fig_timeseries(d, fig_dir / "im_timeseries.png")
    fig_2022(d, fig_dir / "im_2022.png", cfg)
    fig_span_validation(d, fig_dir / "span_validation.png")

    as_of = pd.Timestamp(d.meta["as_of_date"]).date()
    t_today, today = today_table(d)
    v1, v2 = validation_tables(d)
    de, en = interpretation(d, today)
    diag = d.diag
    lines = [
        "# Margin comparison: simplified SPAN vs. Prisma-inspired FHS",
        "", f"> **{BANNER_EN}**", "",
        f"Generated by `make report` on {date.today()} from the local warehouse. As-of date "
        f"(latest REAL ECC file): **{as_of}**. REAL history collected: "
        f"{int(d.meta['real_days'])} business days from "
        f"{pd.Timestamp(d.meta['real_start']).date()}. PROXY history: "
        f"{pd.Timestamp(d.meta['proxy_start']).date()} to "
        f"{pd.Timestamp(d.meta['proxy_end']).date()}.",
        "",
        "**Price sources.** `REAL` = settlement prices and SPAN parameters from ECC's public "
        "daily files (data: EEX via ECC). `PROXY` = synthetic tenor series from SMARD "
        "day-ahead prices (Bundesnetzagentur | SMARD.de, CC BY 4.0), single factor, per-tenor "
        f"scaling {d.meta['proxy_scales']}. This is a Prisma-*inspired* model, not ECC Prisma; "
        "ECC's Prisma calibration is member-only and every parameter here is an assumption "
        "(docs/DECISIONS.md).",
        "",
        f"Data quality: {len(d.quar)} rows quarantined "
        f"({', '.join(f'{k}: {v}' for k, v in d.quar['reason'].value_counts().items()) or 'none'}"
        f"); {len(d.drift)} schema-drift events.",
        "",
        "## 1. Today: IM per portfolio (REAL prices)",
        "",
        "MRIM = market-risk initial margin = max(FHS, SP). All values EUR million.",
        "",
        f"SPAN-current uses ECC's scanning ranges and inter-commodity credits of {as_of} "
        f"(credit file {pd.Timestamp(d.meta_margin['credit_file_date']).date()}). "
        "SPAN-hist applies ECC's "
        "published scanning-range formula to the PROXY history (validated in section 2). FHS "
        "and SP value today's REAL positions under PROXY historical scenarios. *Real-vol* "
        "variant: FHS rescaled to the current volatility of the REAL futures returns "
        "(EWMA, lambda 0.94, over the collected REAL days) instead of the proxy's.",
        "", t_today, "",
        "Source: REAL prices and ECC parameters; FHS/SP scenarios PROXY.",
        "",
        "## 2. Validation of SPAN-hist against real ECC scanning ranges",
        "",
        "Same formula, parameters taken from ECC's risk parameter file, no tuning. Error = "
        "SPAN-hist (formula on PROXY returns x REAL price) / ECC - 1, per REAL day.",
        "", v1, "",
        "Because the proxy is one factor scaled by s_k (taken from ECC's ranges), all tenors "
        "share M1's relative error up to the day-to-day change of ECC's ratios: **only the M1 "
        "row is an independent check**.",
        "", "![SPAN validation](figures/span_validation.png)", "",
        "Formula check on the as-of date: volatility from the REAL returns collected so far "
        "(too few for ECC's 255-return window and for R, so R is backed out instead).",
        "", v2, "",
        "## 3. IM time series and breaches (PROXY)",
        "", "![IM time series](figures/im_timeseries.png)", "",
        "Table view: `fct_backtest_daily` in the warehouse (one row per day, portfolio, model).",
        "",
        "## 4. Backtest summary (PROXY, 99 %, 2-day)",
        "",
        "Breach: realised 2-day loss > IM. Overlapping 2-day windows make breaches dependent "
        "by construction, so the Christoffersen test is also shown on the non-overlapping "
        "subsample (every second day). Single-factor proxy: books with the same sign of net "
        "factor exposure breach on the same days.",
        "", backtest_table(d), "",
        "## 5. Procyclicality (PROXY)",
        "", procyclicality_table(d), "",
        "![IM around August 2022](figures/im_2022.png)", "",
        "## 6. Diversification",
        "", diversification_table(d), "",
        "## 7. How much does the single-factor proxy overstate offsets?",
        "",
        "The proxy has correlation 1 between tenors. Correlations from the REAL returns "
        "collected so far, and the effect on a parametric (variance-covariance) IM of the "
        "spread portfolio with REAL volatilities:",
        "", correlation_table(d), "",
        f"Proxy diagnostics: lag-1 autocorrelation of daily proxy returns "
        f"{diag['proxy_lag1_autocorr']:.2f} (trailing-mean artefact) vs. "
        f"{diag['real_m1_lag1_autocorr']:.2f} for REAL M1 ({int(diag['real_m1_n'])} returns, "
        f"very noisy); daily vol over the last 21 days: PROXY "
        f"{100 * diag['proxy_m1_daily_vol_last21']:.2f} % vs. REAL "
        f"{100 * diag['real_m1_daily_vol_last21']:.2f} %.",
        "",
        "## 8. Was bedeutet das? / What does it mean?",
        "", "**Deutsch**", "", *[f"- {x}" for x in de], "", "**English**", "",
        *[f"- {x}" for x in en], "",
    ]
    (reports / "margin_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    if readme_dir is not None:
        update_readme(readme_dir / "README.md", readme_block(d, today, "de"))
        update_readme(readme_dir / "README.en.md", readme_block(d, today, "en"))
    return {"report": str(reports / "margin_comparison.md"), "figures": 3}
