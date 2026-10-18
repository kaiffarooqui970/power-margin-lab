"""End-to-end smoke test: the full pipeline on deterministic synthetic data (used in CI)."""

import duckdb

from power_margin_lab import pipeline


def test_pipeline_end_to_end(synthetic_root, tmp_path):
    reports = tmp_path / "reports"
    assert pipeline.main(["all", "--data-dir", str(synthetic_root),
                          "--reports-dir", str(reports)]) == 0
    report = (reports / "margin_comparison.md").read_text()
    for section in ("## 1. Today", "## 2. Validation", "## 4. Backtest summary",
                    "## 5. Procyclicality", "## 6. Diversification", "Was bedeutet das?"):
        assert section in report
    assert "PROXY" in report and "REAL" in report
    assert (reports / "figures" / "im_timeseries.png").stat().st_size > 10_000

    con = duckdb.connect(str(synthetic_root / "warehouse.duckdb"), read_only=True)
    q = con.sql("select count(*) from fct_margin_result where price_source is null").fetchone()
    assert q[0] == 0
    sources = {r[0] for r in
               con.sql("select distinct price_source from fct_tenor_series").fetchall()}
    assert sources == {"REAL", "PROXY"}
    # weekly futures (p = 0.00) never reach the settlement table
    weekly = "select count(*) from fct_settlement where product_id like 'DEB1%'"
    assert con.sql(weekly).fetchone()[0] == 0
    n_bt = con.sql("select count(*) from fct_backtest_result").fetchone()[0]
    assert n_bt > 0
    # P3 SPAN-current: spread credit applied (synthetic credit 0.75)
    credit = con.sql("""select value_eur from fct_margin_result where run='today'
                        and model='SPAN-current' and portfolio_id='P3'
                        and component='spread_credit'""").fetchone()[0]
    assert credit > 0
    con.close()
