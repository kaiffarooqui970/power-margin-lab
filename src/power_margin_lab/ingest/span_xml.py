"""Extract German baseload futures from ECC_SPANFILE_<date>.xml.zip (SPAN file format 4.00).

The XML is ~320 MB per day, so it is stream-parsed straight out of the zip with iterparse and
only `futPf` blocks with pfCode DEBM/DEBQ/DEBY are kept. The per-day extract is cached as CSV in
data/interim/span_xml/ (gitignored), so each file is parsed once.

Weekly futures (DEB1-DEB5) carry p = 0.00 in the SPAN file and are out of scope (D-003).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pandas as pd

FIELDS = ["pe", "p", "cvf", "fDeliv", "lDeliv", "setlDate"]
COLUMNS = ["calc_date", "pf_code", *FIELDS, "priceScan"]
NAME_RE = re.compile(r"^ECC_SPANFILE_(\d{8})\.xml\.zip$")
_CLEAR = {"futPf", "ccDef", "oopPf", "ooePf", "phyPf", "oofPf", "currencyDef", "exchange"}


def extract(zip_path: Path, codes: tuple[str, ...] = ("DEBM", "DEBQ", "DEBY")) -> pd.DataFrame:
    m = NAME_RE.match(zip_path.name)
    if not m:
        raise ValueError(f"unexpected SPAN file name {zip_path.name}")
    calc = m.group(1)
    rows = []
    with zipfile.ZipFile(zip_path) as z:
        member = next(n for n in z.namelist() if n.lower().endswith(".xml"))
        with z.open(member) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag == "futPf":
                    code = el.findtext("pfCode")
                    if code in codes:
                        for fut in el.findall("fut"):
                            scan = fut.find("scanRate")
                            rows.append([calc, code, *(fut.findtext(f) for f in FIELDS),
                                         scan.findtext("priceScan") if scan is not None else None])
                if el.tag in _CLEAR:
                    el.clear()
    return pd.DataFrame(rows, columns=COLUMNS, dtype=str)


def extract_cached(zip_path: Path, cache_dir: Path) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / (zip_path.name.replace(".xml.zip", ".csv"))
    if cache.exists() and cache.stat().st_mtime >= zip_path.stat().st_mtime:
        return pd.read_csv(cache, dtype=str, keep_default_na=False)
    df = extract(zip_path)
    df.to_csv(cache, index=False)
    return df


def find_files(raw_ecc: Path) -> list[Path]:
    return sorted(raw_ecc.glob("*/ECC_SPANFILE_*.xml.zip"))
