"""Stage `report`: reports/margin_comparison.md, figures, README result blocks."""

from __future__ import annotations

from .. import warehouse as wh
from ..config import ROOT, Paths
from ..report.build_report import build


def run(paths: Paths, cfg: dict) -> dict:
    paths.reports.mkdir(parents=True, exist_ok=True)
    con = wh.connect(paths.warehouse)
    # README result blocks are only refreshed for the repository's own reports directory
    readme_dir = ROOT if paths.reports.resolve() == (ROOT / "reports").resolve() else None
    out = build(con, paths.reports, cfg, readme_dir)
    con.close()
    return out
