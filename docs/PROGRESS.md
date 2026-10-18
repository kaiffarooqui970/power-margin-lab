# Progress log

**Phase 0: data inspection (2026-10-18)**
- Read ECC margining V1.19, the Guide to Margining, the risk parameter file, the Prisma webinar, the press release, circulars 02/49/69 and the Q3/2026 disclosure. Wrote `background.md`.
- Built the idempotent ECC downloader and inspected all ECC files. German base is DEBM/DEBQ/DEBY; ranges are EUR per lot = EUR/MWh × DST-correct hours; three different number formats; single-expiry tiers, so no intra-commodity charge.
- Open at the time: Energy-Charts exports. Later replaced by the SMARD proxy (licence).

**Phases 1-5: developed in one pass, committed as phase-sized commits after the full suite passed**
- Note: the phases were built together in one session (user instruction: run 1-7 without stopping). Ruff and pytest were run on the combined state before the commits; the intermediate commits were not tested one by one.

**Phase 1: ingestion and contracts**
- YAML schema contracts per raw file, one strict number parser per file convention, quarantine with reasons, schema-drift log; raw_* tables in DuckDB.
- Found and quarantined ECC's 0.01 placeholder prices (pre-listing and post-expiry). Identified the 212 % buffer as G5BQ_06 (gas).
- Found a YAML pitfall (`1.5e12` parsed as a string); the contract loader now rejects non-numeric bounds (D-052).

**Phase 2: data model**
- dim_product with UTC-based delivery hours (all 1,012 SPAN rows match ECC `cvf`), calendar expiry rule verified on 16 observed expiries, tenor mapping with the no-roll rule.
- PriceSource interface: REAL (SPAN file), PROXY (SMARD, single factor, scaled by ECC ranges, anchored to REAL prices), EEX stub.
- DATA_MODEL.md (ERD, grain, lineage) and GLOSSARY.md.

**Phase 3: Prisma-inspired FHS**
- EWMA FHS (λ 0.94 / 0.97), vol floor, 3-year window, overlapping 2-day joint scenarios, VaR 99 % / ES 97.5 %, stress period without look-ahead, MRIM = max(FHS, SP).
- A unit test exposed a flaw: the vol floor used the wrong σ set and bound even at q = 0. Fixed (D-023).
- Added the "real-vol" today variant (D-029) after the proxy's vol was found to be below real futures vol.

**Phase 4: simplified SPAN**
- ECC SMP formula with ECC's published parameters (SPAN-hist, no tuning), 16-scenario scan risk, inter-tier credits that reproduce ECC's Guide example exactly, and the intra-commodity charge (zero for ECC power tiers).
- SPAN-current from real ECC ranges and credits; SPAN-hist credits held at the latest file per tenor pair, with an overlap variant for M1 ⊂ Q1.
- Open: SPAN-hist is about 25 % below the real ranges because the proxy vol is low. Reported, not tuned.

**Phase 5: validation**
- Kupiec, Christoffersen (all days and non-overlapping), traffic light (last and worst 250), procyclicality, diversification, SPAN-hist vs. ECC, implied-R formula check, REAL-correlation bias check of the proxy.
- Finding: max(FHS, SP) is conservative on the proxy (SP binds), while pure FHS is close to nominal coverage.

**Phase 6: report**
- `make report` writes reports/margin_comparison.md, 3 figures and the README result blocks. Every number is read from warehouse tables, and every table names its price source.
- Interpretation sentences are generated from the numbers, including their direction (e.g. "too few breaches").

**Phase 7: documentation and polish**
- German and English READMEs with status banner, METHODOLOGY, LIMITATIONS, DECISIONS (D-001 to D-053), MIT licence.
- CI (ruff + pytest including the end-to-end smoke test on synthetic fixtures); macOS LaunchAgent for the daily ECC download.
- Open: real EEX history (stub ready); a longer REAL history from the daily job; a multi-factor proxy or real data to remove the correlation-1 bias.

**Pre-publish review (2026-10-18)**
- Proxy volatility explained: the 30-day trailing mean smooths spot volatility heavily, so the proxy's volatility level is set by the window. Documented in METHODOLOGY, LIMITATIONS, DECISIONS D-011 and report §2, with a generated table for windows of 1, 7 and 30 days.
- Report: 95 % intervals (chi-square, Fisher-z) and bootstrap ranges for the short REAL estimates; the anti-procyclicality trade-off table (breaches, mean uplift, SP-binding share, peak/trough, 5-day jumps); finding 1 reworded as conservative by design.
- Licence audit of public files; GitHub user and citation/contact section added.
