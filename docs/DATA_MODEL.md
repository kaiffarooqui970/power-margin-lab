# Data model

Local DuckDB warehouse `data/warehouse.duckdb` (gitignored). The layers are:

- **raw_\***: validated copies of source files.
- **int_\***: intermediate aggregates.
- **dim_\* / fct_\***: the domain model.
- **meta_\* / dq_\* / quarantine**: run metadata and data quality.

Every fact that carries prices or results has a `price_source` column (`REAL` | `PROXY`).

## ERD (domain model)

```mermaid
erDiagram
    dim_product ||--o{ fct_settlement : "priced by"
    dim_product ||--o{ fct_tenor_series : "mapped to tenor"
    dim_product ||--o{ fct_span_parameter : "scanning range of"
    dim_product ||--o{ fct_spread_credit : "leg A / leg B"
    dim_portfolio ||--o{ fct_position : holds
    dim_portfolio ||--o{ fct_margin_result : "margined as"
    dim_portfolio ||--o{ fct_backtest_daily : "backtested as"
    dim_portfolio ||--o{ fct_backtest_result : "summarised as"
    fct_position }o--|| fct_tenor_series : "tenor resolves to product per date"

    dim_product {
        varchar product_id PK "DEBM-2026-11 / DEBQ-2027-Q1 / DEBY-2027"
        varchar ecc_code "DEBM | DEBQ | DEBY"
        varchar load_type "base"
        varchar delivery_type "M | Q | Y"
        date delivery_start
        date delivery_end
        int delivery_hours "UTC-based, DST-correct"
        int ecc_contract_hours "cvf from SPAN file (check)"
        date ecc_last_trading_day "setlDate from SPAN file"
        date rule_last_trading_day "calendar rule D-006"
    }
    fct_settlement {
        date trade_date PK
        varchar product_id PK,FK
        varchar price_source PK "REAL"
        double price "EUR/MWh"
        varchar source_file
    }
    fct_tenor_series {
        date trade_date PK
        varchar tenor PK "M1..Y2"
        varchar price_source PK "REAL | PROXY"
        varchar product_id FK
        double price "EUR/MWh"
        double ret_1d "within one contract"
        int delivery_hours
    }
    dim_portfolio {
        varchar portfolio_id PK "P1..P5"
        varchar name
    }
    fct_position {
        varchar portfolio_id PK,FK
        varchar tenor PK
        double mw
        int sign
        double signed_mw
    }
    fct_span_parameter {
        date as_of_date PK
        varchar product_id PK,FK
        varchar model PK "ECC | SPAN-hist"
        date valid_date "ECC: next business day"
        double scan_eur_per_lot
        double scan_eur_per_mwh
        varchar price_source
    }
    fct_spread_credit {
        date as_of_date PK
        varchar product_id_a PK,FK
        varchar product_id_b PK,FK
        bigint spread_id
        double ratio_a
        double ratio_b
        double credit
    }
    fct_margin_result {
        date as_of_date PK
        varchar run PK "today | history"
        varchar portfolio_id PK "P1..P5 or leg P3:Y1"
        varchar model PK "SPAN-current | SPAN-hist | FHS | FHS-l097 | SP | MRIM | *-realvol"
        varchar component PK "scan_risk | spread_credit | im | var | es"
        double value_eur
        varchar price_source
        varchar scenario_source
        varchar window_flag "full | short"
        double window_obs
        varchar binding "FHS | SP (MRIM only)"
    }
    fct_backtest_daily {
        date as_of_date PK
        varchar portfolio_id PK
        varchar model PK
        double im
        double pnl_2d
        double loss_2d
        boolean breach
        varchar price_source
    }
    fct_backtest_result {
        varchar portfolio_id PK
        varchar model PK
        bigint n_obs
        bigint breaches
        double kupiec_p
        double christoffersen_p
        varchar zone_last_250
        varchar price_source
    }
```

`fct_position` references tenors, not products. The product is resolved per date through
`fct_tenor_series`, which is the mapping table, so a position "long Y1" always points to the
contract that is Y1 on that date.

## Grain and keys

| Table | Grain (one row per …) | Key |
|---|---|---|
| raw_ecc_scanning_range | ECC file × product code × expiry | calc_date, product_code, expiry_year, expiry_month |
| raw_ecc_margin_buffer | ECC file × product × relative maturity | calc_date, product_maturity |
| raw_ecc_spread_credit | spreads file × tier pair (German base subset) | calc_date, spread_id |
| raw_ecc_span_settlement | SPAN file × German base futures contract | calc_date, pf_code, period |
| raw_smard_hourly | delivery hour (UTC ms) | ts_ms |
| int_smard_daily_base | Berlin delivery day | delivery_day |
| dim_product | contract (delivery period) | product_id |
| fct_settlement | trade date × contract × source | trade_date, product_id, price_source |
| fct_tenor_series | trade date × tenor × source | trade_date, tenor, price_source |
| dim_portfolio | portfolio | portfolio_id |
| fct_position | portfolio × tenor | portfolio_id, tenor |
| fct_span_parameter | as-of date × contract × model | as_of_date, product_id, model |
| fct_span_hist_detail | trade date × tenor (σ, R, b, SMP) | trade_date, tenor |
| fct_spread_credit | as-of date × contract pair | as_of_date, product_id_a, product_id_b |
| fct_ecc_margin_buffer | as-of date × ECC code × relative maturity | as_of_date, ecc_code, relative_maturity |
| fct_margin_result | date × run × book × model × component | as_of_date, run, portfolio_id, model, component |
| fct_backtest_daily | date × book × model | as_of_date, portfolio_id, model |
| fct_backtest_result | book × model | portfolio_id, model |
| fct_procyclicality | portfolio × model | portfolio_id, model |
| fct_diversification | portfolio × run × model | portfolio_id, run, model |
| fct_span_validation(_daily) | tenor (× trade date) | tenor (, trade_date) |
| fct_span_formula_check | tenor, as-of date | tenor |
| fct_correlation_check | spread portfolio | portfolio_id |
| quarantine | rejected source row | (contract, source_file, raw_record) |
| meta_schema_drift | drift event | (contract, source_file) |

"Book" means a portfolio or one of its single legs (`P3:Y1`), which are needed for
diversification ratios.

## Lineage

```mermaid
flowchart LR
    subgraph Sources
        A1[ECC scanning ranges CSV]
        A2[ECC margin buffer CSV]
        A3[ECC inter-commodity spreads CSV]
        A4[ECC SPAN XML zip]
        B1[SMARD day-ahead JSON]
    end
    A1 -->|contract + DE parser| R1[raw_ecc_scanning_range]
    A2 -->|percent parser| R2[raw_ecc_margin_buffer]
    A3 -->|DE-base filter, dot parser| R3[raw_ecc_spread_credit]
    A4 -->|stream parse, cache| R4[raw_ecc_span_settlement]
    B1 --> R5[raw_smard_hourly]
    R1 & R2 & R3 & R4 & R5 -.->|rejected rows| Q[quarantine]
    R5 --> I1[int_smard_daily_base]
    R4 --> S[fct_settlement REAL]
    R4 --> P[dim_product]
    S -->|EccSpanFileSource| T[fct_tenor_series]
    I1 -->|SmardProxySource, anchored + scaled by ECC ranges| T
    R1 --> SP[fct_span_parameter]
    R3 --> C[fct_spread_credit]
    R2 --> MB[fct_ecc_margin_buffer]
    T & SP & C --> M[fct_margin_result]
    M --> BT[fct_backtest_daily / _result]
    M --> PC[fct_procyclicality / fct_diversification]
    T & SP & MB --> V[fct_span_validation / formula_check / correlation_check]
    BT & PC & V --> REP[reports/margin_comparison.md + README result block]
```

Stages: `ingest` (raw_\*, quarantine, drift) → `build` (dim/fct up to fct_tenor_series) →
`margin` → `backtest` → `report`.
