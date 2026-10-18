"""SMARD day-ahead prices for the DE-LU bidding zone (filter 4169), hourly resolution.

Source: Bundesnetzagentur | SMARD.de, licensed CC BY 4.0
(https://www.smard.de/home/datennutzung). The raw weekly JSON files are stored locally under
data/raw/smard/hour/ and are not committed.

API (undocumented but public, used by the SMARD web app):
  index:  https://www.smard.de/app/chart_data/4169/DE-LU/index_hour.json   -> weekly timestamps
  week:   https://www.smard.de/app/chart_data/4169/DE-LU/4169_DE-LU_hour_<ts>.json
          -> {"series": [[ts_ms_utc, price_or_null], ...]}
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from ..contracts.validate import apply_contract, load_contract
from ..model.products import BERLIN, delivery_hours

BASE = "https://www.smard.de/app/chart_data/4169/DE-LU"
USER_AGENT = "power-margin-lab/0.1 (personal research)"


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def download(dest: Path, start: date, refresh_last: int = 2) -> int:
    """Fetch weekly files from `start`; existing files are skipped except the newest
    `refresh_last` weeks, which may still be incomplete. Returns number of files fetched."""
    dest.mkdir(parents=True, exist_ok=True)
    start_ms = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp() * 1000)
    stamps = [ts for ts in _get_json(f"{BASE}/index_hour.json")["timestamps"]
              if ts >= start_ms - 7 * 86400 * 1000]
    fetched = 0
    for i, ts in enumerate(stamps):
        target = dest / f"{ts}.json"
        if target.exists() and i < len(stamps) - refresh_last:
            continue
        tmp = target.with_suffix(".part")
        tmp.write_text(json.dumps(_get_json(f"{BASE}/4169_DE-LU_hour_{ts}.json")))
        tmp.replace(target)
        fetched += 1
        time.sleep(0.05)
    return fetched


def load_hourly(src: Path):
    """All weekly files -> validated hourly frame (ts_ms, price) + quarantine + drift."""
    rows = []
    for f in sorted(src.glob("*.json")):
        for ts, price in json.loads(f.read_text())["series"]:
            if price is not None:  # future hours are null
                rows.append((str(ts), repr(float(price))))
    raw = pd.DataFrame(rows, columns=["ts_ms", "price"]).drop_duplicates("ts_ms")
    return apply_contract(raw, load_contract("raw_smard_hourly"), f"{src.name}/*.json")


def daily_baseload(hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Arithmetic mean of hourly prices per Europe/Berlin delivery day.

    Days with fewer hours than the local day length (23/24/25) are rejected, not averaged.
    """
    ts = pd.to_datetime(hourly["ts_ms"].astype("int64"), unit="ms", utc=True)
    local = ts.dt.tz_convert(BERLIN)
    df = pd.DataFrame({"delivery_day": local.dt.date, "price": hourly["price"].astype(float)})
    g = df.groupby("delivery_day")["price"].agg(["mean", "count"]).reset_index()
    expected = g["delivery_day"].map(lambda d: delivery_hours(d, d))
    ok = g["count"] == expected
    good = g[ok].rename(columns={"mean": "base_price", "count": "n_hours"})
    bad = g[~ok].assign(reason=lambda x: "incomplete day: " + x["count"].astype(str) + " of "
                        + expected[~ok].astype(str) + " hours")
    return good.reset_index(drop=True), bad.reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    from ..config import get_paths

    p = argparse.ArgumentParser(description="Download SMARD DE-LU day-ahead prices (hourly)")
    p.add_argument("--start", default="2018-10-01")
    args = p.parse_args(argv)
    n = download(get_paths().raw_smard / "hour", date.fromisoformat(args.start))
    print(f"SMARD: fetched {n} weekly files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
