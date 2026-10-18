# Known limitations

Read this before using any number from `reports/`.

1. **Not affiliated with ECC.** This is not ECC Prisma and not ECC's SPAN implementation. "Prisma-inspired" means only the structure published in ECC's June 2026 webinar: FHS + stress period, max, 99 %, 2-day MPOR, 3-year window. ECC's Prisma calibration, TE files and replication guide are member-only, so all FHS parameters here are assumptions (DECISIONS D-020+).
2. **Baseload only.** German baseload Month/Quarter/Year futures only. No peak, weekend or week contracts (weekly futures carry a price of 0.00 in the SPAN file anyway), no options, no other markets, and no cross-commodity credits in practice.
3. **Historical analysis uses a proxy, not futures.** EEX futures history is not yet available to this project; Energy-Charts data may not be used. All backtests and procyclicality results run on a synthetic tenor series built from SMARD **day-ahead spot** prices (30-day trailing mean). The consequences:
   - **One factor:** tenor correlation is 1, so FHS spread offsets are overstated. For the calendar spread the report quantifies this with the REAL correlation (§7).
   - **The construction smooths volatility.** The base factor is a 30-day trailing *average* of spot prices. This removes most of spot's (much higher) daily volatility, so the proxy's volatility level is set by the averaging window, not measured. Today it is below real futures volatility; that gap is an artefact of the window choice, not evidence that spot is calmer than futures (report §2 shows the effect of the window). SPAN-hist levels, FHS volatility scaling and backtest outcomes all inherit it. History also includes spot spikes that futures would not show one-to-one.
   - The trailing mean creates **positively autocorrelated returns**, which inflates volatility clustering and Christoffersen rejections.
   - Per-tenor scales come from ECC's current scanning ranges. The proxy therefore inherits ECC's view of relative tenor risk, and SPAN-hist validation is independent only for M1.
4. **REAL history is short.** ECC publishes about one month of files. REAL-based statistics (volatility, correlations, the "real-vol" FHS variant, the implied risk multiplier) rest on about 21 daily returns and are very noisy; the report gives 95 % intervals and bootstrap ranges (§7). Run the daily download (README) to extend them.
5. **ECC data as a secondary source.** REAL settlement prices are read from ECC's SPAN file, i.e. EEX data via ECC. They are not EEX's official settlement-price publication. They are used locally and never committed. The "today" IMs are derived from ECC's public parameter files and are shown for illustration.
6. **SPAN-hist is a proxy.**
   - It applies ECC's formula to proxy returns, holds inter-commodity credits constant at the latest file, and ignores ECC's bootstrap correlation correction and Combined-Commodity tiering beyond single expiries.
   - It is validated, not tuned. The observed gap to the real ranges is reported as is.
7. **Simplified SPAN.** Futures-only scan risk and inter-tier credits. No options, no volatility scan, no short-option minimum, no perfect-spread decomposition (ECC's file encodes month-in-quarter as a regular credit), no concentration margin (CONR), no delivery or additional margins.
8. **Simplified FHS.** No liquidity, concentration or delivery risk as ECC models them. No compression-model or portfolio-margining adjustment, no liquidation groups, no weighting of contracts in delivery (they are excluded instead). The stress window is a single fixed period chosen by hand.
9. **Backtest design.** Overlapping 2-day windows make breaches dependent; non-overlapping tests are shown alongside. The constant-maturity proxy has no contract rolls. Positions are held constant over the MPOR.
10. **Trading calendar** approximates EEX/ECC holidays (D-005).
