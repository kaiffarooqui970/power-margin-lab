"""Stage `ingest`: raw files -> validated raw_* tables, quarantine, schema-drift log."""

from __future__ import annotations

import json

import pandas as pd

from .. import warehouse as wh
from ..config import Paths
from ..contracts.validate import apply_contract, load_contract
from ..ingest import ecc_csv, smard, span_xml


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run(paths: Paths, cfg: dict) -> dict:
    con = wh.connect(paths.warehouse)
    quarantine, drift, counts = [], [], {}

    def collect(name, results):
        valid = _concat([r[0] for r in results])
        quarantine.extend(r[1] for r in results)
        for r in results:
            drift.extend(r[2])
        wh.write(con, name, valid)
        counts[name] = len(valid)

    collect("raw_ecc_scanning_range",
            [ecc_csv.load_scanning_ranges(f) for f in ecc_csv.find_files(paths.raw_ecc,
                                                                         "scanningranges")])
    collect("raw_ecc_margin_buffer",
            [ecc_csv.load_margin_buffer(f) for f in ecc_csv.find_files(paths.raw_ecc,
                                                                       "MarginBuffer")])
    collect("raw_ecc_spread_credit",
            [ecc_csv.load_spread_credits(f) for f in ecc_csv.find_files(
                paths.raw_ecc, "intercommodityspreads")])

    contract = load_contract("raw_ecc_span_settlement")
    collect("raw_ecc_span_settlement",
            [apply_contract(span_xml.extract_cached(f, paths.interim / "span_xml"), contract,
                            f.name) for f in span_xml.find_files(paths.raw_ecc)])

    hourly, q_h, d_h = smard.load_hourly(paths.raw_smard / "hour")
    quarantine.append(q_h)
    drift.extend(d_h)
    wh.write(con, "raw_smard_hourly", hourly)
    counts["raw_smard_hourly"] = len(hourly)
    daily, bad_days = smard.daily_baseload(hourly)
    wh.write(con, "int_smard_daily_base", daily)
    counts["int_smard_daily_base"] = len(daily)
    if len(bad_days):
        quarantine.append(pd.DataFrame({
            "contract": "int_smard_daily_base", "source_file": "raw_smard_hourly",
            "reason": bad_days["reason"],
            "raw_record": bad_days.drop(columns="reason").to_json(orient="records", lines=True)
            .splitlines()}))

    q = _concat(quarantine)
    if q.empty:
        q = pd.DataFrame(columns=["contract", "source_file", "reason", "raw_record"])
    wh.write(con, "quarantine", q)
    wh.write(con, "meta_schema_drift", pd.DataFrame(
        drift, columns=["contract", "source_file", "missing_columns", "unexpected_columns",
                        "detected_at"], dtype=str))
    log = paths.data / "logs" / "schema_drift.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        for e in drift:
            f.write(json.dumps(e) + "\n")
    counts["quarantine"] = len(q)
    counts["schema_drift_events"] = len(drift)
    con.close()
    return counts
