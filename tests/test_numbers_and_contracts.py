import pandas as pd
import pytest

from power_margin_lab.contracts import validate
from power_margin_lab.contracts.validate import ContractError, apply_contract, load_contract
from power_margin_lab.ingest.numbers import parse_de_decimal, parse_dot_decimal, parse_percent


@pytest.mark.parametrize("s,expected", [("3.993,84", 3993.84), ("893,62", 893.62),
                                        ("126.319,20", 126319.20), ("1.234", 1234.0),
                                        ("0,20", 0.2), ("12", 12.0), ("-1.234,5", -1234.5)])
def test_de_decimal(s, expected):
    assert parse_de_decimal(s) == pytest.approx(expected)


@pytest.mark.parametrize("s", ["3993.84", "1,234.5", "3.99,84", "", "abc", "25.00%"])
def test_de_decimal_rejects_other_formats(s):
    with pytest.raises(ValueError):
        parse_de_decimal(s)


@pytest.mark.parametrize("s,expected", [("0.73", 0.73), ("14.42", 14.42), ("3", 3.0)])
def test_dot_decimal(s, expected):
    assert parse_dot_decimal(s) == expected


@pytest.mark.parametrize("s", ["1,5", "1.234,5", "0.73%"])
def test_dot_decimal_rejects(s):
    with pytest.raises(ValueError):
        parse_dot_decimal(s)


def test_percent():
    assert parse_percent("25.00%") == pytest.approx(0.25)
    assert parse_percent("211.82%") == pytest.approx(2.1182)
    for bad in ("25.00", "25,00%"):
        with pytest.raises(ValueError):
            parse_percent(bad)


SR_COLS = ["Product_ID", "Expiry_Year", "Expiry_Month", "ClearingCurrency", "PriceScanRange",
           "Volscanrange"]


def _sr(rows, cols=SR_COLS):
    return pd.DataFrame(rows, columns=cols, dtype=str)


def test_scanning_range_contract_valid_and_quarantine():
    raw = _sr([["DEBM", "2026", "11", "EUR", "20.246,40", "0,20"],
               ["DEBM", "2026", "12", "EUR", "17684.88", "0,20"],      # dot decimal -> parse error
               ["DEBQ", "2027", "13", "EUR", "1,00", "0,20"],          # month out of range
               ["DEBY", "2027", "01", "EUR", "-5,00", "0,20"]])        # negative range
    valid, q, drift = apply_contract(raw, load_contract("raw_ecc_scanning_range"), "x.csv")
    assert len(valid) == 1 and valid.loc[0, "price_scan_range"] == pytest.approx(20246.40)
    assert len(q) == 3 and not drift
    reasons = " | ".join(q["reason"])
    assert "parse error" in reasons and "expiry_month: above max" in reasons
    assert "price_scan_range: below min" in reasons


def test_schema_drift_extra_column_logged():
    raw = _sr([["DEBM", "2026", "11", "EUR", "20.246,40", "0,20", "x"]], SR_COLS + ["NewCol"])
    valid, q, drift = apply_contract(raw, load_contract("raw_ecc_scanning_range"), "drift.csv")
    assert len(valid) == 1
    assert drift[0]["unexpected_columns"] == "NewCol" and drift[0]["missing_columns"] == ""


def test_schema_drift_missing_required_column_raises():
    raw = _sr([["DEBM", "2026", "11", "EUR", "0,20"]],
              [c for c in SR_COLS if c != "PriceScanRange"])
    with pytest.raises(ContractError):
        apply_contract(raw, load_contract("raw_ecc_scanning_range"), "drift.csv")


def test_span_placeholder_price_is_quarantined():
    cols = ["calc_date", "pf_code", "pe", "p", "cvf", "fDeliv", "lDeliv", "setlDate", "priceScan"]
    raw = pd.DataFrame([["20260929", "DEBQ", "202610", "0.01", "2209", "20261001", "20261231",
                         "20260928", "43340.58"],
                        ["20260929", "DEBQ", "202701", "188.02", "2159", "20270101", "20270331",
                         "20261229", "49419.51"]], columns=cols)
    valid, q, _ = apply_contract(raw, load_contract("raw_ecc_span_settlement"), "s.zip")
    assert len(valid) == 1 and "not above 0.01" in q.loc[0, "reason"]


def test_contract_rejects_non_numeric_bounds(tmp_path, monkeypatch):
    (tmp_path / "bad.yml").write_text(
        "name: bad\nsource_columns: [a]\ncolumns:\n  a: {source: a, type: float, max: 1.0e9}\n")
    monkeypatch.setattr(validate, "SCHEMA_DIR", tmp_path)
    with pytest.raises(ContractError, match="must be numeric"):
        load_contract("bad")
