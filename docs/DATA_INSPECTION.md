# Phase 0: raw file inspection notes

Describes file *formats* only; no values from licensed sources are reproduced here.

## ECC public files (inspected 2026-10-18, window 2026-09-17 … 2026-10-16, 22 business days)

**File naming.** `<calc_date>_<kind>_<valid_date>.csv`. `calc_date` is the business day the parameters were computed on; the files are published about 20:00 CET that evening. `valid_date` is the next ECC business day, e.g. `20260918_…_20260921` is Fri→Mon. The MarginBuffer `ReportDate` column equals `calc_date`. The SPAN XML carries `calc_date` only, plus a `<created>` timestamp.

**`scanningranges`**
- Encoding and layout: ASCII, CRLF, `;`-separated, **German number format** (`.` for thousands, `,` for decimals).
- Columns: `Product_ID;Expiry_Year;Expiry_Month;ClearingCurrency;PriceScanRange;Volscanrange`.
- **`PriceScanRange` is EUR per lot**. For German power base, a lot is 1 MW × the delivery hours of the contract. Dividing by the DST-correct hours gives a value with exactly 2 decimals in EUR/MWh. This was checked for every DEBM/DEBQ/DEBY row on 20261016, against the `cvf` field of the SPAN XML.

**`MarginBuffer`**
- Layout: `;`-separated with **`.` decimals plus a `%` suffix**, which differs from the scanning ranges file.
- Columns: `ReportDate (dd.mm.yyyy);ProductID_RelativeMaturity;MarginBuffer`.
- Keyed by **relative (constant) maturity** (`DEBM_00` … `DEBM_24`), not by expiry. Values mostly lie in [0, 25 %], but the file-wide maximum is >200 %. Presumably that is the stressed-volatility buffer component b⁰, which is not capped at 25 %; this needs confirming.

**`intercommodityspreads`** (~55 MB/day, ~1.09 M rows)
- Layout: `;`-separated, `.` decimals.
- Columns: `SpreadID;CombinedCommodityA;ExpiryYearA;ExpiryMonthA;CombinedCommodityB;ExpiryYearB;ExpiryMonthB;TierNumberA;TierNumberB;RatioA;RatioB;Credit`.
- For DE base pairs `RatioA` equals the EUR/MWh scan range of leg **B**, and vice versa. These are the risk-weighted spread ratios of methodology §5.5.1 (a = M_Y, b = M_X).
- 882 rows have German base on both legs. Credits range from 0.38 to 0.98.

**`ECC_SPANFILE_*.xml.zip`** (~20 MB zipped, ~320 MB XML, SPAN file format 4.00)
- Per futures contract: `pe`, settlement price `p`, `cvf` (= hours), `sc`, `fDeliv`/`lDeliv`, `setlDate`, `priceScan` and the 16-point risk array.
- Each expiry is its own scan tier. `intraTiers` is empty for DEBM/DEBQ/DEBY, so **no intra-commodity charge applies**.
- Weekly futures (DEB1–DEB5) show `p = 0.00`.

**German power product codes.** Names are taken from the SPAN XML.
- `DEBM`, `DEBQ`, `DEBY`: EEX German Power Base Month/Quarter/Year Future.
- `DEB1`–`DEB5`: Base Week 1–5 Future.
- `DEPx`: Peak.
- `DEWx`: Weekend Block.
- Germany has no `F1`/Phelix DE/AT codes any more.

**Delivery and cascading.**
- Quarters and years **expire before delivery** (`setlDate` lies in the last days before `fDeliv`). Neither has a `_00` (in-delivery) maturity, so they cascade.
- Months are listed **during** their delivery month (DEBM `_00`), with the full-month `cvf`.

**Risk parameter file.** The *Model Parametrisation* sheet gives the SMP calibration: λ, look-back, R_min, R_max, α_R, w, a, MCAP. The *Cross Margining* sheet maps DE power to liquidation group `COREN`, cross-margining group `ENERGY`.

**Placeholder price 0.01 (found in Phase 1).** In the SPAN XML, contracts carry p = 0.01 (ECC's
"Minimum Settlement Price" in the risk parameter file) in two cases:
- newly listed far contracts before their first settlement (DEBM 2028-10, DEBQ 2029-Q3);
- cascaded contracts after their last trading day (DEBQ 2026-Q4, DEBM 2026-09).

Left in, these rows would produce a −99.99 % return. They are quarantined by the contract
(`exclusive_min: 0.01`); rows after `setlDate` are also dropped in `build`.

**The ~212 % margin buffer.** It is `G5BQ_06`, the 6th relative maturity of
**EEX PEG Natural Gas Quarter Future** (name confirmed in the SPAN XML), on 2026-10-16. Values of 202 % (17.09) and 205 %
(01.10) show it is persistent. The stressed-volatility component
`b0 = (5/255)(σ_max/σ − 1)` gives 211.82 % for σ_max/σ ≈ 109, i.e. current volatility at about
1 % of its historical maximum (a thinly traded back quarter). No German power entry exceeds 25 %.

## Energy-Charts exports

Not used: the export is not licensed for this use (user decision, 2026-10-18).

## SMARD day-ahead (inspected 2026-10-18)

- API: `https://www.smard.de/app/chart_data/4169/DE-LU/index_hour.json` returns weekly timestamps; each weekly file holds `{"meta_data": {...}, "series": [[ts_ms_utc, price|null], ...]}`. Hourly resolution remains available after the 2025 switch to 15-minute day-ahead products; a `quarterhour` series also exists.
- Coverage: 2018-09-30 22:00 UTC (= 2018-10-01 local) to the latest auction. Future hours are `null`.
- Quality: no duplicate hours; hourly min −500, max ≈ 936 EUR/MWh; every Berlin delivery day is complete (23/24/25 hours).
- Licence: CC BY 4.0, attribution "Bundesnetzagentur | SMARD.de" (https://www.smard.de/home/datennutzung).

## Pitfall reproduced during inspection

Subtracting two `datetime`s that share the same `ZoneInfo("Europe/Berlin")` gives **wall-clock** duration and ignores DST: Oct = 744 h instead of the correct 745. Delivery hours must be computed in UTC. `tests/` will assert March = 743 h, October = 745 h, Q1 (non-leap) = 2159 h and leap Cal = 8784 h.
