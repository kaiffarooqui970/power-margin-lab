"""Pipeline CLI: python -m power_margin_lab.pipeline <stage> [--data-dir ...] [--reports-dir ...]

Stages: download, ingest, build, margin, backtest, report, all (= all but download).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date

from .config import get_paths, load_model_config


def _dates(cfg: dict) -> dict:
    """YAML gives dates as date objects already; make sure nested ones are, too."""
    for sec, keys in {"stress": ("start", "end"), "procyclicality": ("start", "end", "base"),
                      "history": ("start",)}.items():
        for k in keys:
            if sec in cfg and isinstance(cfg[sec].get(k), str):
                cfg[sec][k] = date.fromisoformat(cfg[sec][k])
    return cfg


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("stage", choices=["download", "ingest", "build", "margin", "backtest",
                                     "report", "all"])
    p.add_argument("--data-dir")
    p.add_argument("--reports-dir")
    p.add_argument("--config-dir")
    args = p.parse_args(argv)
    paths = get_paths(args.data_dir, args.reports_dir, args.config_dir)
    cfg = _dates(load_model_config(paths))

    from .stages import backtest_run, build, ingest, margin_run, report_run

    stages = {"ingest": ingest.run, "build": build.run, "margin": margin_run.run,
              "backtest": backtest_run.run, "report": report_run.run}
    if args.stage == "download":
        from .ingest import ecc_files, smard
        ecc_files.main(["--dest", str(paths.raw_ecc), "--date", "all", "--with-spanfile"])
        # SPAN-current needs the inter-commodity credits of the latest day (~55 MB, latest only)
        ecc_files.main(["--dest", str(paths.raw_ecc), "--date", "latest", "--with-spreads"])
        n = smard.download(paths.raw_smard / "hour", cfg["history"]["start"])
        print(f"SMARD: fetched {n} weekly files")
        return 0
    todo = list(stages) if args.stage == "all" else [args.stage]
    for name in todo:
        t0 = time.time()
        out = stages[name](paths, cfg)
        print(f"[{name}] {time.time() - t0:.1f}s {json.dumps(out, default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
