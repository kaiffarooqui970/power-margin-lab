# Background: initial margin at ECC, SPAN → ECC Prisma for Commodities

*Sources read on 2026-10-18. Bracketed numbers refer to the list at the end. This project is not affiliated with ECC; where the text below says "ECC does X" it paraphrases ECC's public documents only.*

## What SPAN does at ECC today

- **Scope and target.** SPAN® covers futures and options on the derivatives market and is calibrated to a **99 % confidence level** over a **2-business-day liquidation period**, applied to all products [1, §2.2]. Concentration risk margin (CONR) is charged on top for positions whose liquidation would take longer than 2 days, with the liquidation period capped at 3 days [1, §4.2].
- **Scanning range = Single Margin Parameter (SMP).** For futures the worst-case loss is driven only by the price scan range. That range is the SMP times the contract volume [1, §4.1.3]:
  `M_X = p_X · σ_X · √l_X · R_X · (1 + b_X) · W_X` (the add-on `a_X` is 0) [1, §4.1.2.1]. Here σ is an EWMA volatility of **relative** daily returns over the 255 most recent non-zero returns, λ = 0.99 [1, §5.1]. R is a risk multiplier: the average of the |1 %| and |99 %| quantiles of volatility-normalised returns, floored at 2.66 and capped at 3.5 [1, §5.2; 4]. b is an anti-procyclicality buffer, max(stressed-vol component with weight w = 5/255, a 25 % buffer that tapers off above σ_crit) [1, §5.3; 4].
- **Constant maturities.** Returns and parameters are computed per *constant maturity* (front month, second month, …). Each history therefore chains different contracts [1, §4.1.1].
- **Scenarios.** The standard 16 CME scan points (price ±⅓, ±⅔, ±1 × range with vol up/down, plus ±3 × range at weight 0.33) are used without customisation [1, §4.1.3, Table 1].
- **Offsets.** Perfect spreads (fully overlapping delivery, e.g. a year against its quarters) get a 99 % credit. Intra-commodity charges are defined for multi-expiry tiers. Inter-commodity credits `C_P = min(1 − M_P/M̃_P, cap)` come from a volatility-normalised historical simulation of a risk-weighted synthetic spread. The cap is 80 % between different commodities (power vs. gas) and 99 % otherwise [1, §4.1.4, §5.5]. ECC's worked example: `IM = M_x + M_y − 2·IC·min(M_x, M_y)` [3, p. 14].
- **Units.** Scanning ranges are **EUR per lot**. Example: DEBM 01-2026 = 6,919.20 EUR per lot on 25.11.2025 [3, p. 13].

## What ECC Prisma for Commodities changes

- **Portfolio VaR instead of per-product scan risk.** The model is the commodity version of Eurex Clearing's Prisma, running on Deutsche Börse's R7 platform [2; 5; 6].
- **Components** [5, p. 7]:
  - **Market-risk IM (MRIM).** The overview diagram shows MRIM as the **max** of a **Filtered Historical Simulation (FHS)** VaR and a **Stress Period (SP)** simulation. FHS uses **99 %** confidence, a **2-day MPOR** and a **3-year** observation window. SP is meant to capture "extreme market conditions that may lie outside the current observation window".
  - **Compression Model Adjustment (CMA)**, which corrects for the risk-factor compression.
  - A **Liquidity Adjustment (LA)**, which includes concentration. ECC computes it per market rather than per instrument [5, p. 8].
  - A **Portfolio Margining Adjustment (PMA)**, which steers how much offset is granted.
  - Positions are grouped into **Liquidation Groups / Liquidation Group Splits**. The cross-margining sheet of the risk parameter file puts German power in liquidation group `COREN` [4].
- **Commodity-specific design** [5, p. 8]:
  - Risk factors account for overlapping delivery profiles and negative prices.
  - A weighting function in the P&L reflects the decreasing risk of contracts **in delivery**. It is published as a new TE file, WGFCT.
  - Calibration is ECC's own.
- **Timeline.**
  - The parallel production run started on **19 Oct 2026** [7].
  - Members receive "Prisma Hypothetical Reports" (CP9xx) next to the binding SPAN margin [8].
  - Full migration is planned for **March 2027**, after which SPAN is no longer supported [7; 8].

## Which parameters are public, and which are not

| Parameter | Public value | Source |
|---|---|---|
| Confidence level, MPOR | 99 %, 2 days (both models) | [1, §2.2], [5, p. 7] |
| FHS observation window | 3 years | [5, p. 7] |
| MRIM aggregation | max(FHS, SP) (diagram) | [5, p. 7] |
| SPAN SMP: λ, look-back, R_min/R_max, α_R, w, a, MCAP | 0.99, 256, 2.66/3.5, 0.99, 5, 0.2, 0.8 | [4] (sheet *Model Parametrisation*) |
| Daily SPAN scanning ranges, APC margin buffers, inter-commodity credits, full SPAN file | ~1 month rolling | [9] |
| **Prisma: EWMA λ, volatility floor, stress-period dates, LA/PMA/CMA formulas, risk-factor definitions, in-delivery weights** | **not public**: the *User Guide for Margin Replication* and the TE files sit in the members-only section; production TE files have been listed as unavailable [6; 8; 10] | n/a |

**Consequence for this project.** The SPAN side can be rebuilt fairly closely from public material. The Prisma side cannot. The FHS model here follows the published *structure* (FHS + SP, max, 99 %, 2-day MPOR, 3-year window). Every unpublished detail is a standard choice logged in `docs/DECISIONS.md`. It is a **Prisma-inspired** model, not ECC Prisma.

## References

1. ECC, *ECC Derivative Market Margining*, Version 1.19. <https://www.ecc.de/fileadmin/ECC/Downloads/Risk_Management/Margining/ECC_Derivative_Market_Margining_V1.19.pdf>
2. ECC, Press release "ECC advances transition to portfolio-based initial margin model", 9 Jan 2026. <https://www.ecc.de/fileadmin/Global/News/ECC/ECC_Press_Release/2026/20260109_R7Prisma_final.pdf>
3. ECC, *A Guide to Margining at ECC*, Sep 2026. <https://www.ecc.de/fileadmin/ECC/Downloads/Risk_Management/Margining/20260910_A_Guide_to_Margining_at_ECC.pdf>
4. ECC, *ECC Risk Parameters* (xlsx, last update 14 Sep 2026). <https://www.ecc.de/fileadmin/Global/Upload/Upload_ECC_Risk_Parameters/ECC_Risk_Parameters.xlsx>
5. ECC, *Webinar ECC Prisma for Commodities*, 25 Jun 2026. <https://www.ecc.de/fileadmin/ECC/Access/Prisma_Migration/Webinar_ECC_Prisma_for_Commodities_June_2026.pdf>
6. ECC Clearing Circular 02/2026, 9 Jan 2026. <https://www.ecc.de/fileadmin/Global/News/ECC/ECC_Circulars/2026/20260109_ECC_Clearing_Circular_No._02_ECC_Prisma_for_Commodities.pdf>
7. ECC Clearing Circular 69/2026, 24 Sep 2026. <https://www.ecc.de/fileadmin/Global/News/ECC/ECC_Circulars/2026/ECC_Clearing_Circular_No._69_ECC_Prisma_for_Commodities_update_to_parallel_run_start_timeline.pdf>
8. ECC Clearing Circular 49/2026, 17 Jul 2026. <https://www.ecc.de/fileadmin/Global/News/ECC/ECC_Circulars/2026/20260717_ECC_Clearing_Circular_No._49_Parallel_Run_Start.pdf>
9. ECC public reports and files index. <https://public.eex-group.com/ecc/risk-management/reports-files/index.html>
10. ECC, *ECC Prisma for Commodities: Known Limitations*. <https://www.ecc.de/fileadmin/ECC/Access/Prisma_Migration/List_of_Known_Limitations.pdf>

Also consulted: ECC, *Back and Stress Testing Disclosure Report Q3/2026* (2 Oct 2026). It reports daily portfolio backtesting with the Basel traffic light, and no derivatives portfolio in the red zone in Q3/2026. <https://www.ecc.de/fileadmin/ECC/Downloads/Risk_Management/Margining/2026Q3_Back_stress_testing_disclosure.pdf>
