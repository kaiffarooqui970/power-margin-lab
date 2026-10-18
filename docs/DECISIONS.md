# Decision log

Every methodological choice, with its reason. IDs are referenced from the code. "ECC" sources:
*Derivative Market Margining V1.19* [MM], *Risk Parameters* xlsx [RP], *A Guide to Margining*
Sep 2026 [GM], *Prisma webinar* Jun 2026 [WB]. Details that ECC does not publish are marked
**assumption**.

## Data and scope

| ID | Decision | Reason |
|---|---|---|
| D-001 | No raw or licensed data in git: `data/` and `*.duckdb` are gitignored. Energy-Charts is **not used**; its data may not be exported for this use. | Licences: EEX/ECC data needs permission for systematic republication; Energy-Charts allows personal use only. |
| D-002 | Models consume one `PriceSource` interface (tenor series). Three implementations: REAL (ECC SPAN-file settlements), PROXY (SMARD), EEX/LSEG (stub). | Lets the source be swapped once EEX history is available, without touching models. Every result row stores `price_source`. |
| D-003 | Scope is German baseload Month/Quarter/Year futures (DEBM/DEBQ/DEBY). Weeks (DEB1-5), peak (DEP*) and weekend blocks (DEW*) are out of scope. | As in the brief. The SPAN file also carries **price 0.00 for weekly futures**, so they could not be valued anyway. |
| D-004 | SPAN-file prices of exactly 0.01 are quarantined. Rows listed after their `setlDate` are dropped. | 0.01 is ECC's "Minimum Settlement Price" [RP]. It appears on newly listed contracts before their first settlement and on cascaded contracts after expiry (24 rows in Sep-Oct 2026). Left in, it produced a -99.99 % "return". |
| D-005 | Trading calendar: Mon-Fri without 1 Jan, Good Friday, Easter Monday, 1 May, 24-26 Dec (**assumption**). | ECC's holiday calendar is not in the files. This calendar is consistent with the 22 observed file dates and all observed expiries. |
| D-006 | When no listing is known, quarters and years expire 3 business days before delivery start. | Matches all 16 DEBQ/DEBY `setlDate`s checked in the 2026-10-16 SPAN file (unit-tested). |
| D-007 | Tenor Mk/Qk/Yk = k-th listed contract whose delivery has **not started**. Contracts in delivery are excluded. | Simplest correct treatment. Only months are ever in delivery, because quarters and years expire before delivery (observed). ECC's in-delivery weighting (WGFCT) is member-only [WB p. 8]. |
| D-008 | Returns are always within one contract (t-1 → t). A missing previous price gives a missing return, never a cross-roll return. | Brief. Unit-tested on an M1 roll. |
| D-009 | Delivery hours = UTC difference of Berlin local midnights. | Same-ZoneInfo datetime subtraction ignores DST (gives 744 h for October). Tests: Mar 743 h, Oct 745 h, Q1 2159 h, leap year 8784 h. All 1,012 SPAN contract rows match ECC's `cvf`. |

## PROXY history (SMARD)

| ID | Decision | Reason |
|---|---|---|
| D-010 | Base data: SMARD day-ahead DE-LU (filter 4169), hourly, from 2018-10-01 (start of the bidding zone). Daily baseload = mean of the hours of the Berlin delivery day. Incomplete days are quarantined. | Free, licensed CC BY 4.0 ("Bundesnetzagentur \| SMARD.de"). Hourly series exist on SMARD across the switch to 15-minute day-ahead products in 2025. |
| D-011 | Base risk factor = **30-calendar-day trailing mean** of daily baseload, sampled on business days. | A month future prices an average over a month; a trailing mean is the simplest spot-derived stand-in that removes weekday and weather noise. Known artefact: the overlapping window makes returns positively autocorrelated (quantified in the report). |
| D-012 | Per-tenor return scaling `s_k = (scan/price)_k / (scan/price)_M1` from ECC's scanning ranges on the as-of date. | User's suggestion. It gives the proxy ECC's current *relative* term structure of risk. Consequence: SPAN-hist validation across tenors is not independent; only M1 is. |
| D-013 | Proxy levels are compounded from the scaled returns and anchored to the REAL price of each tenor on the as-of date. The series is constant-maturity, so it has no rolls. | Makes price levels and hence EUR exposures comparable to REAL on the as-of date. |
| D-014 | Risk-factor returns are **relative (arithmetic)**, not absolute price changes. | Consistent with ECC's SMP [MM §5.1]. A relative move scales with the price level, which matters when history spans 50-600 EUR/MWh. FHS devolatisation partly neutralises the difference anyway. Negative prices, the case for absolute returns, do not occur in the futures or in the 30-day proxy factor (min > 0 is checked). |

## Prisma-inspired FHS (ECC's real parameters are member-only; all values below are assumptions unless cited)

| ID | Decision | Reason |
|---|---|---|
| D-020 | Structure: FHS + stress period, MRIM = max(FHS, SP), 99 %, 2-day MPOR, 3-year window. | [WB p. 7]. Everything else is an assumption. ECC's *User Guide for Margin Replication* and TE files are in the members-only section [Circular 02/2026]. |
| D-021 | EWMA λ = 0.94 (default), 0.97 as sensitivity. | Brief. 0.94 is the RiskMetrics daily standard; 0.97 is a slower alternative. |
| D-022 | EWMA seeded with the mean square of the first 20 returns. Devolatised `z_s = r_s/σ_{s-1}`. Current vol σ_T includes r_T. | Standard FHS convention (Barone-Adesi et al.). Avoids look-ahead in z. |
| D-023 | Vol floor = 5 % quantile of the σ values used for devolatising in the window, applied to the denominators and to σ_T. | Prevents near-zero vol from blowing up z or collapsing IM. With q = 0 the floor switches off (a unit test caught an earlier version that used the wrong σ set and bound even at q = 0). |
| D-024 | 2-day scenarios = overlapping compounded 2-day filtered returns. Window = scenario end dates in (t − 3 calendar years, t]. At least 250 scenarios. Dates with < 3 years of history are flagged `short` and excluded from the backtest statistics. | Brief. Full windows exist from 2021-11-01 with SMARD history from 2018-10. |
| D-025 | Stress window 2021-09-01 … 2023-03-31 (energy crisis). Unfiltered scenarios, 99 % quantile, only scenarios ≤ t (no look-ahead), at least 20 scenarios; otherwise SP is unavailable and MRIM = FHS. | Brief. ECC's stress-period definition is not public. |
| D-026 | VaR quantile = empirical order statistic (inverted CDF). ES 97.5 % = mean of losses ≥ the 97.5 % quantile. | Transparent and hand-checkable (unit test). With a few hundred SP scenarios this produces visible step changes when the order statistic switches. |
| D-027 | Liquidity add-on implemented (`rate × gross notional`) but **off** by default. | A gross-notional add-on is not ECC's market-level LA [WB p. 8]. Switching it on would only blur the SPAN/FHS comparison. |
| D-028 | Joint scenarios across tenors on the same date. | Preserves cross-tenor dependence; the source of portfolio offsets. In the PROXY all tenors are one factor, so offsets are overstated (D-044). |
| D-029 | Extra "today" variant `FHS-realvol`: σ_T from REAL futures returns (EWMA 0.94 over the collected REAL days), shocks from the proxy. Shown next to, not instead of, the main FHS. | The proxy's current vol is below real futures vol (report §2). This variant shows how much that matters today. It is based on about 21 returns, so it is noisy. |

## SPAN

| ID | Decision | Reason |
|---|---|---|
| D-030 | SPAN-hist = ECC's SMP formula `p·σ·√2·R·(1+b)` [MM §4.1.2.1, §5.1-5.3] with ECC's parameters [RP]: λ 0.99, 255 non-zero returns, α_R 0.99, R ∈ [2.66, 3.5] (R_max if < 100 obs), w = 5, a = 0.2, 25 % buffer. W = 1 (financial futures, no EMF). Rounded to 2-decimal EUR/MWh × hours. **No tuning to match ECC.** | User decision A. Rounding: every observed DE-base range is a 2-decimal EUR/MWh value × hours. |
| D-031 | σ_min/σ_max for the buffer use the σ history with ≥ 100 observations. With no observed vol range the full 25 % buffer applies (numerical tolerance). | ECC says "all available data" [MM §5.3]; early σ on tiny samples would distort the range. The tolerance avoids float-noise buffers (found by a unit test). |
| D-032 | Portfolio SPAN for futures: scan risk = worst of the 16 scenarios per contract (= |lots| × range) [MM §4.1.3]. Intra-commodity charge = 0, because ECC's power tiers are single-expiry (`intraTiers` empty in the SPAN XML); the formula is still implemented and tested. Inter-tier credits use ECC's spread file, applied in descending order as `IM = M_x + M_y − 2·C·min(M_x, M_y)` [GM p. 14]. | Matches ECC's worked example exactly (unit test). With ECC's risk-weighted ratios (RatioA = scan of leg B, observed) this equals SPAN spread formation. |
| D-033 | SPAN-current = ECC's scanning ranges and credits of the as-of date (REAL). Used only for "today". | Brief. |
| D-034 | SPAN-hist credits: held constant at the latest ECC file per tenor pair. When the contracts overlap (M1 inside Q1, in the last month of each quarter) the latest credit of the analogous overlapping pair is used (first month of the current Q1). | ECC publishes about 1 month of credits. Re-estimating credits on the single-factor proxy would give ≈ 99 % credits (correlation 1). |
| D-035 | No separate perfect-spread step. | ECC's file already encodes month-inside-quarter as a regular credit (e.g. 0.89 observed for Jan-27/Q1-27), not 99 %. Perfect spreads in ECC's sense (fully overlapping, e.g. year vs. its 4 quarters) do not occur in the test portfolios. |
| D-036 | Concentration margin (CONR), additional margins and the delivery margin are excluded from both models. | Out of the brief's market-risk scope; listed in LIMITATIONS. |

## Validation

| ID | Decision | Reason |
|---|---|---|
| D-040 | Backtest: positions fixed at t, realised P&L over (t, t+2] on the constant-maturity proxy. Breach if loss > IM(t). Statistics only on full-window dates. | Standard IM backtest at the MPOR horizon. |
| D-041 | Christoffersen and Kupiec are also reported on the non-overlapping subsample (every 2nd day). | Overlapping 2-day windows create serial dependence by construction. |
| D-042 | Traffic light on the last 250 observations and on the worst rolling 250-day window. | Brief (green 0-4, yellow 5-9, red ≥ 10). ECC uses the Basel traffic light for its daily portfolio backtests (disclosure report Q3/2026). |
| D-043 | Procyclicality: peak/trough, maximum 5- and 30-business-day increase, and the Jul-Sep 2022 peak relative to 1 Jul 2022, all on full-window dates. | Brief. Business-day steps keep the metrics independent of weekends. |
| D-044 | Proxy correlation bias quantified with REAL correlations (Fisher-z 95 % CI) and a parametric variance-covariance IM ratio ρ_real vs. ρ = 1. | The only REAL evidence available on cross-tenor dependence is the collected SPAN-file history. |
| D-045 | Diversification ratio = IM(portfolio) / Σ IM(single legs), same model and date. | Brief. |

## Engineering

| ID | Decision | Reason |
|---|---|---|
| D-050 | One strict number parser per file convention (German decimal, dot decimal, percent). | The three ECC files use three conventions. A lenient parser would read German "1.234" as 1.234. |
| D-051 | Contracts: a missing required column fails the run; extra columns are logged as drift (`meta_schema_drift`, `data/logs/schema_drift.jsonl`); invalid rows go to `quarantine` with a reason. | Fail loudly on what cannot be interpreted, continue on additive changes. |
| D-052 | The contract loader rejects non-numeric bounds. | PyYAML 1.1 parses `1.5e12` as a *string*, which silently broke a range check during development. |
| D-053 | Daily ECC download via a macOS LaunchAgent with `--date all` (idempotent). | Catches up on missed days within ECC's ~1-month window if the Mac was asleep; launchd runs missed jobs on wake. |
