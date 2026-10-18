from datetime import date

import numpy as np
import pandas as pd
import pytest

from power_margin_lab.ingest import ecc_files, smard, span_xml
from power_margin_lab.sources.eex import EexHistorySource
from power_margin_lab.sources.smard_proxy import SmardProxySource, tenor_scales

INDEX_HTML = """<table>
<tr><td><a href="20261015_scanningranges_20261016.csv">x</a></td></tr>
<tr><td><a href="20261016_MarginBuffer_20261019.csv">x</a></td></tr>
<tr><td><a href="20261016_scanningranges_20261019.csv">x</a></td></tr>
<tr><td><a href="20261016_intercommodityspreads_20261019.csv">x</a></td></tr>
<tr><td><a href="ECC_SPANFILE_20261016.xml.zip">x</a></td></tr>
<tr><td><a href="..">..</a></td></tr></table>"""


def test_parse_index_and_select_latest():
    files = ecc_files.parse_index(INDEX_HTML)
    assert {f.kind for f in files} == {"scanningranges", "MarginBuffer",
                                       "intercommodityspreads", "spanfile"}
    sel = ecc_files.select(files, {"scanningranges", "MarginBuffer"}, "latest")
    assert {f.name for f in sel} == {"20261016_MarginBuffer_20261019.csv",
                                     "20261016_scanningranges_20261019.csv"}
    assert all(f.valid_date == "20261019" for f in sel)
    assert len(ecc_files.select(files, {"scanningranges"}, "all")) == 2


def test_download_is_idempotent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ecc_files, "_get", lambda url, timeout=0: calls.append(url) or b"a;b\n")
    f = ecc_files.RemoteFile("20261016_scanningranges_20261019.csv", "scanningranges",
                             "20261016", "20261019")
    assert ecc_files.download(f, tmp_path)[1] is True
    assert ecc_files.download(f, tmp_path)[1] is False
    assert len(calls) == 1 and not list(tmp_path.rglob("*.part"))


def test_daily_baseload_dst_and_incomplete():
    # 2027-03-28 has 23 hours (UTC 2027-03-27 23:00 .. 2027-03-28 22:00)
    start = pd.Timestamp("2027-03-27 23:00", tz="UTC")
    ts = [start + pd.Timedelta(hours=i) for i in range(23)]
    # plus 5 hours of the next day (incomplete)
    ts += [ts[-1] + pd.Timedelta(hours=i) for i in range(1, 6)]
    hourly = pd.DataFrame({"ts_ms": [int(t.timestamp() * 1000) for t in ts],
                           "price": [10.0] * 23 + [99.0] * 5})
    good, bad = smard.daily_baseload(hourly)
    assert list(good["delivery_day"]) == [date(2027, 3, 28)]
    assert good["n_hours"].iloc[0] == 23 and good["base_price"].iloc[0] == 10.0
    assert "incomplete day" in bad["reason"].iloc[0]


def test_span_xml_extract_skips_weekly(synthetic_root):
    f = sorted(synthetic_root.glob("raw/ecc/*/ECC_SPANFILE_*.xml.zip"))[0]
    df = span_xml.extract(f)
    assert set(df["pf_code"]) == {"DEBM", "DEBQ", "DEBY"}
    assert (df["cvf"].astype(float) > 0).all()


def _daily(n=120, start=date(2026, 1, 1)):
    days = pd.date_range(start, periods=n, freq="D")
    rng = np.random.default_rng(0)
    return pd.DataFrame({"delivery_day": days.date,
                         "base_price": 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))})


def test_proxy_scales_and_anchor():
    anchor = pd.DataFrame({"tenor": ["M1", "Y1"], "price": [200.0, 100.0],
                           "scan_eur_per_mwh": [30.0, 10.0]})
    s = tenor_scales(anchor)
    assert s["M1"] == 1.0 and s["Y1"] == pytest.approx((10 / 100) / (30 / 200))
    daily = _daily()
    src = SmardProxySource(daily, anchor, date(2026, 4, 1), smoothing_days=30)
    ts = src.tenor_series(["M1", "Y1"]).set_index(["trade_date", "tenor"])
    assert ts.loc[(date(2026, 4, 1), "M1"), "price"] == pytest.approx(200.0)
    assert ts.loc[(date(2026, 4, 1), "Y1"), "price"] == pytest.approx(100.0)
    m1 = ts.xs("M1", level="tenor")["ret_1d"].dropna()
    y1 = ts.xs("Y1", level="tenor")["ret_1d"].dropna()
    assert np.allclose(y1.to_numpy(), s["Y1"] * m1.to_numpy())
    assert (ts["price_source"] == "PROXY").all()
    # level path is consistent with returns
    p = ts.xs("M1", level="tenor")["price"]
    assert (p / p.shift(1) - 1).dropna().to_numpy() == pytest.approx(m1.to_numpy()[0:][
        -len((p / p.shift(1) - 1).dropna()):])


def test_eex_stub_explains_itself():
    with pytest.raises(NotImplementedError, match="README"):
        EexHistorySource("data/raw/eex").tenor_series(["M1"])
