"""Deterministic synthetic raw data in the exact formats of the real files (seed 42).

Used by CI: no real price data is ever in the repository. Writes into <root>/raw/...:
- smard/hour/<ts>.json      SMARD weekly JSON ({"meta_data":..., "series": [[ts_ms, price]]})
- ecc/<date>/..._scanningranges_...csv   German decimals, CRLF
- ecc/<date>/..._MarginBuffer_...csv     percent strings
- ecc/<date>/..._intercommodityspreads_...csv (last date only)
- ecc/<date>/ECC_SPANFILE_<date>.xml.zip minimal SPAN 4.00 structure (futPf/fut)
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from power_margin_lab.model.products import BERLIN, Product, business_days, last_trading_day
from power_margin_lab.model.tenors import candidate_products

SMARD_START = date(2018, 10, 1)
SMARD_END = date(2023, 6, 30)
ECC_DATES = business_days(date(2023, 6, 21), date(2023, 6, 29))


def _de(x: float) -> str:
    s = f"{x:,.2f}"                      # 12,345.67
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def listed(t: date) -> list[Product]:
    out = [Product(date(t.year, t.month, 1), "M")]              # month in delivery
    out += candidate_products(t, "M", 6)
    out += [p for p in candidate_products(t, "Q", 5) if t <= last_trading_day(p)][:4]
    out += [p for p in candidate_products(t, "Y", 4) if t <= last_trading_day(p)][:3]
    return out


def write_smard(root: Path, rng: np.random.Generator) -> np.ndarray:
    days = (SMARD_END - SMARD_START).days + 1
    shocks = rng.standard_t(4, days) * 0.03
    vol_regime = np.where((np.arange(days) > 1050) & (np.arange(days) < 1600), 3.0, 1.0)
    level = 50 * np.exp(np.cumsum(shocks * vol_regime) * 0.6)
    out = root / "raw" / "smard" / "hour"
    out.mkdir(parents=True, exist_ok=True)
    start = datetime(SMARD_START.year, SMARD_START.month, SMARD_START.day, tzinfo=BERLIN)
    t = start.astimezone(UTC)
    end = datetime(SMARD_END.year, SMARD_END.month, SMARD_END.day,
                   tzinfo=BERLIN).astimezone(UTC) + timedelta(days=1)
    series = []
    while t < end:
        d = t.astimezone(BERLIN).date()
        lvl = level[(d - SMARD_START).days]
        series.append([int(t.timestamp() * 1000), round(float(lvl * (1 + 0.2 * rng.normal())), 2)])
        t += timedelta(hours=1)
    for i in range(0, len(series), 168):
        chunk = series[i:i + 168]
        (out / f"{chunk[0][0]}.json").write_text(json.dumps(
            {"meta_data": {"version": 1}, "series": chunk}))
    return level


def write_ecc(root: Path, rng: np.random.Generator, spot_level: float) -> None:
    prices: dict[str, float] = {}
    for i, d in enumerate(ECC_DATES):
        valid = ECC_DATES[i + 1] if i + 1 < len(ECC_DATES) else d + timedelta(days=1)
        folder = root / "raw" / "ecc" / f"{d:%Y%m%d}"
        folder.mkdir(parents=True, exist_ok=True)
        prods = listed(d)
        for p in prods:
            prices[p.product_id] = prices.get(p.product_id, spot_level * rng.uniform(0.8, 1.2)) \
                * (1 + 0.02 * rng.normal())
        tag = f"{d:%Y%m%d}"
        # scanning ranges (+ two non-DE rows)
        lines = ["Product_ID;Expiry_Year;Expiry_Month;ClearingCurrency;PriceScanRange;Volscanrange",
                 "G3BM;2023;08;EUR;2.328,72;0,20", "FEUA;2023;12;EUR;7.060,00;0,20"]
        rel = {"M": 0.14, "Q": 0.12, "Y": 0.10}
        for p in prods:
            scan = round(prices[p.product_id] * rel[p.delivery_type], 2) * p.delivery_hours
            lines.append(f"{p.ecc_code};{p.delivery_start.year};{p.delivery_start.month:02d};"
                         f"EUR;{_de(scan)};0,20")
        (folder / f"{tag}_scanningranges_{valid:%Y%m%d}.csv").write_bytes(
            ("\r\n".join(lines) + "\r\n").encode("ascii"))
        mb = ["ReportDate;ProductID_RelativeMaturity;MarginBuffer"]
        for code, n in (("DEBM", 7), ("DEBQ", 5), ("DEBY", 4)):
            for k in range(n):
                mb.append(f"{d:%d.%m.%Y};{code}_{k:02d};{rng.uniform(15, 25):.2f}%")
        (folder / f"{tag}_MarginBuffer_{valid:%Y%m%d}.csv").write_bytes(
            ("\r\n".join(mb) + "\r\n").encode("ascii"))
        # SPAN XML
        futs = []
        for p in prods:
            futs.append((p, prices[p.product_id]))
        xml = ["<spanFile><fileFormat>4.00</fileFormat><definitions></definitions><pointInTime>"]
        for code in ("DEBM", "DEBQ", "DEBY", "DEB1"):
            xml.append(f"<futPf><pfId>1</pfId><pfCode>{code}</pfCode><name>synthetic</name>")
            for p, px in futs:
                if p.ecc_code != code:
                    continue
                setl = p.delivery_end if p.delivery_type == "M" else last_trading_day(p)
                scan = round(px * rel[p.delivery_type], 2) * p.delivery_hours
                xml.append(
                    f"<fut><cId>1</cId><pe>{p.delivery_start:%Y%m}</pe><p>{px:.2f}</p>"
                    f"<cvf>{p.delivery_hours}.0000000</cvf><setlDate>{setl:%Y%m%d}</setlDate>"
                    f"<fDeliv>{p.delivery_start:%Y%m%d}</fDeliv><lDeliv>{p.delivery_end:%Y%m%d}"
                    f"</lDeliv><scanRate><r>1</r><priceScan>{scan:.6f}</priceScan>"
                    f"<volScan>0.2</volScan></scanRate></fut>")
            if code == "DEB1":
                xml.append("<fut><pe>202307</pe><p>0.00</p><cvf>168</cvf></fut>")
            xml.append("</futPf>")
        xml.append("</pointInTime></spanFile>")
        with zipfile.ZipFile(folder / f"ECC_SPANFILE_{tag}.xml.zip", "w",
                             zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"ECC_SPANFILE_{tag}.xml", "\n".join(xml))
        if i == len(ECC_DATES) - 1:
            sp = ["SpreadID;CombinedCommodityA;ExpiryYearA;ExpiryMonthA;CombinedCommodityB;"
                  "ExpiryYearB;ExpiryMonthB;TierNumberA;TierNumberB;RatioA;RatioB;Credit",
                  "1;FEUA;2023;12;FEUA;2024;12;;;7.06;6.87;0.99"]
            sid = 2
            trad = [p for p in prods if p.delivery_start > d]
            for a in range(len(trad)):
                for b in range(a + 1, len(trad)):
                    pa, pb = trad[a], trad[b]
                    credit = 0.89 if (pa.contains(pb) or pb.contains(pa)) else 0.75
                    sp.append(f"{sid};{pa.ecc_code};{pa.delivery_start.year};"
                              f"{pa.delivery_start.month:02d};{pb.ecc_code};"
                              f"{pb.delivery_start.year};{pb.delivery_start.month:02d};;;"
                              f"10.00;12.00;{credit}")
                    sid += 1
            (folder / f"{tag}_intercommodityspreads_{valid:%Y%m%d}.csv").write_bytes(
                ("\r\n".join(sp) + "\r\n").encode("ascii"))


def make(root: Path, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    level = write_smard(root, rng)
    write_ecc(root, rng, float(level[-30:].mean()))
    return root


if __name__ == "__main__":
    import sys

    print(make(Path(sys.argv[1])))
