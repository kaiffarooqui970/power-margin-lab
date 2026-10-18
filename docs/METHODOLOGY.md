# Methodology (10-minute read)

**What this is.** A reproducible comparison of two initial-margin (IM) models for portfolios of
German baseload power futures:

- a **simplified SPAN** that follows ECC's published methodology, and
- a **Prisma-inspired FHS** that follows the published *structure* of ECC Prisma for
  Commodities.

**What it is not.** A replication of ECC Prisma. Its calibration, risk-factor design,
in-delivery weights and liquidity/concentration components are member-only. Decision IDs (D-xxx)
point to `DECISIONS.md`; results are in `reports/margin_comparison.md`.

## 1. Data and the REAL / PROXY split

| | REAL | PROXY |
|---|---|---|
| Source | ECC public daily files: SPAN XML (settlement price, contract hours, scanning range per contract), scanning ranges CSV, margin buffer CSV, inter-commodity spreads CSV | SMARD day-ahead prices DE-LU, hourly (Bundesnetzagentur \| SMARD.de, CC BY 4.0) |
| History | ~1 month published by ECC; grows with the daily download job | 2018-10 to today |
| Used for | "Today": prices, hours, ECC scanning ranges and credits; validation of SPAN-hist; tenor correlations | All historical scenarios: FHS/SP scenarios, SPAN-hist volatility, backtest, procyclicality |

Each result row records `price_source` (where prices and exposures come from) and
`scenario_source` (where the historical shocks come from). The "today" FHS is therefore
*REAL prices × PROXY scenarios*. EEX/LSEG futures history can be plugged in later through the
same interface (`sources/eex.py`). Every model then runs on REAL history unchanged.

**Proxy construction (D-010 to D-013).**
1. Daily baseload = mean of hourly day-ahead prices per Berlin delivery day.
2. Base factor X = 30-day trailing mean, sampled on business days.
3. Return r = X_t/X_{t-1} − 1.
4. Tenor k return = s_k · r, where s_k is tenor k's relative scanning range (range/price) divided by M1's, from ECC's file on the as-of date.
5. Levels are anchored to the REAL price on the as-of date.

This is the simplest defensible proxy, and it is **one factor**. Correlation between tenors is
1 by construction, so spread offsets are overstated (quantified in report §7). Spot-derived
volatility is not futures volatility (report §2), and the trailing mean makes returns
autocorrelated.

## 2. Products, tenors and the data model

- **Contracts.** Each contract is identified by its delivery period (`DEBM-2026-11`, `DEBQ-2027-Q1`, `DEBY-2027`). Delivery hours are computed in UTC from Berlin midnights (DST: Mar 743 h, Oct 745 h; D-009). They match ECC's contract volume `cvf` for every contract in the SPAN files.
- **Tenors.** M1, M2, M3, Q1, Q2, Y1 and Y2 map, per trade date, to the k-th listed contract whose delivery has not started (D-007). Quarters and years expire three business days before delivery (D-006), so only months ever enter delivery, and those are excluded. **Returns are always computed within one contract** (D-008).
- **Exposure.** Positions are in MW. P&L = MW × delivery hours × ΔF, with ΔF = F · relative return.
- **Data model.** See `DATA_MODEL.md` for the ERD, the grain of each table and the lineage.

## 3. Prisma-inspired FHS (D-020 to D-029)

For evaluation date T and each tenor k:

1. **EWMA volatility:** σ²_t = λσ²_{t-1} + (1−λ)r²_t, with λ = 0.94 (0.97 as sensitivity).
2. **Devolatise:** z_s = r_s / max(σ_{s-1}, floor). The floor is the 5 % quantile of the σ values used in the window.
3. **Rescale:** r̃_s = z_s · max(σ_T, floor).
4. **2-day scenario** ending at s: (1 + r̃_s)(1 + r̃_{s-1}) − 1, for all s in the last 3 years (overlapping). All tenors use the **same historical dates**, so portfolio offsets come from joint history.
5. **Loss** = −Σ_k MW_k · h_k · F_k(T) · r̃2_{s,k}. FHS = empirical 99 % quantile of losses; ES 97.5 % is also reported.
6. **Stress period (SP):** unfiltered 2-day returns from Sep 2021 to Mar 2023, with only scenarios ≤ T (no look-ahead); 99 % quantile.
7. **Market-risk IM:** MRIM = max(FHS, SP) [ECC webinar p. 7]. The binding component is recorded.

The liquidity add-on is implemented but off (D-027). There is no concentration, compression-model
or portfolio-margining adjustment. Dates with < 3 years of history are computed on the shorter
window and flagged `short`; they are excluded from the statistics (D-024).

**Why max(FHS, SP) behaves as it does here.** SP applies the 2022 relative moves to today's
prices without filtering. In calm periods it is far above FHS, so it binds most of the time
and acts as an anti-procyclical floor. With only a few hundred SP scenarios, the 99 % quantile
is the 2nd to 5th largest loss. That causes visible step changes when the order statistic
switches.

## 4. Simplified SPAN (D-030 to D-036)

**Scanning range (SMP)**, ECC Derivative Market Margining V1.19 §4.1.2.1 / §5.1-5.3, with ECC's
parameters from the Risk Parameters file:

    M = p · σ · √2 · R · (1 + b)

- σ: EWMA (λ = 0.99) over the 255 most recent **non-zero** relative returns.
- R: ½(|q₁%(z)| + |q₉₉%(z)|) of the returns normalised by the previous σ, bounded to [2.66, 3.5]; R_max with < 100 observations.
- b: anti-procyclicality buffer, max(stressed-vol component (5/255)(σ_max − σ)/σ, a 25 % buffer that is reduced linearly above σ_crit = σ_min + 0.2(σ_max − σ_min)).
- Units: rounded to 2-decimal EUR/MWh, then × delivery hours = EUR per lot (1 MW), the unit of ECC's files.

**Portfolio SPAN.**
- Scan risk = worst of the 16 standard scan scenarios per contract, which for futures is |lots| × range.
- ECC's German power tiers contain a single expiry each, so the intra-commodity charge is zero. It is implemented and unit-tested anyway.
- Calendar offsets come only from inter-tier credits: `IM = M_x + M_y − 2·C·min(M_x, M_y)` [ECC Guide p. 14], applied in descending credit order.

**Two variants.**
- **SPAN-current:** ECC's real scanning ranges and credits on the as-of date. "Today" only.
- **SPAN-hist:** the SMP formula applied to the PROXY history, so scanning ranges vary over time. Credits are held at the latest ECC file per tenor pair (D-034). It is used for backtesting, because ECC publishes only about one month of parameters. It is **validated, not calibrated**, against the real ranges (report §2).

## 5. Validation (D-040 to D-045)

- **Backtest:** IM(t) vs. the realised loss over (t, t+2]; breach if loss > IM. On PROXY history from the first full-window date.
  - **Kupiec POF** (unconditional coverage at 1 %).
  - **Christoffersen** independence, on all days and on the non-overlapping subsample.
  - **Basel traffic light** per 250 observations (last 250 and worst rolling 250).
- **Procyclicality:** peak/trough IM, maximum 5- and 30-day increase, and the Jul-Sep 2022 peak relative to 1 Jul 2022.
- **Diversification:** IM(portfolio) / Σ IM(legs), for SPAN and FHS.
- **SPAN-hist vs. ECC:** daily error per tenor over the REAL days. The formula is also checked by backing out the risk multiplier implied by ECC's range, from REAL volatility and ECC's published buffer.
- **Proxy bias:** REAL tenor correlations with a Fisher-z CI, the resulting parametric IM ratio vs. ρ = 1, and the autocorrelation of proxy vs. REAL returns.
- **Data validation:** YAML schema contracts per raw file, quarantine table with reasons, schema-drift log, and consistency checks of SPAN contract hours and delivery dates.

## 6. What was not done

- No ECC Prisma components beyond MRIM: no liquidity adjustment at market level, no concentration, no CMA, no PMA, no liquidation-group logic, and no in-delivery weighting (WGFCT).
- No CONR, delivery margin or additional margins on the SPAN side; no options.
- No peak, week or weekend products, and no cross-commodity portfolios.
- No real futures history: all historical statements rest on the single-factor SMARD proxy.
- The FHS calibration (λ, floor, stress window) is not ECC's and was not optimised.
