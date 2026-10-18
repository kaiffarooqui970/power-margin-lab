"""Download ECC's public daily SPAN parameter files into data/raw/ecc/YYYYMMDD/.

ECC publishes a rolling window of roughly one month at
https://public.eex-group.com/ecc/risk-management/reports-files/index.html

File naming (observed 2026-10-18): ``<calc_date>_<kind>_<valid_date>.csv`` where calc_date is the
business day the parameters were computed on (published ~20:00 CET that evening) and valid_date is
the next ECC business day, on which they apply (Fri 20260918 -> Mon 20260921). The SPAN XML file
carries only calc_date. Files are stored under data/raw/ecc/<calc_date>/.

For local use only. The files are not to be committed or republished; run this daily via cron to
build up a history (see README).
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

INDEX_URL = "https://public.eex-group.com/ecc/risk-management/reports-files/index.html"
BASE_URL = INDEX_URL.rsplit("/", 1)[0] + "/"
DEFAULT_DEST = Path("data/raw/ecc")
USER_AGENT = "power-margin-lab/0.1 (personal research; local use)"

_CSV_RE = re.compile(
    r"^(?P<calc>\d{8})_(?P<kind>scanningranges|MarginBuffer|intercommodityspreads)_(?P<valid>\d{8})\.csv$"
)
_SPAN_RE = re.compile(r"^ECC_SPANFILE_(?P<calc>\d{8})\.xml\.zip$")
_HREF_RE = re.compile(r'href="([^"/?]+)"')

DEFAULT_KINDS = ("scanningranges", "MarginBuffer")


@dataclass(frozen=True)
class RemoteFile:
    name: str
    kind: str
    calc_date: str
    valid_date: str | None


def parse_index(html: str) -> list[RemoteFile]:
    """Extract known ECC parameter files from the directory listing HTML."""
    files: dict[str, RemoteFile] = {}
    for name in _HREF_RE.findall(html):
        if m := _CSV_RE.match(name):
            files[name] = RemoteFile(name, m["kind"], m["calc"], m["valid"])
        elif m := _SPAN_RE.match(name):
            files[name] = RemoteFile(name, "spanfile", m["calc"], None)
    return sorted(files.values(), key=lambda f: (f.calc_date, f.kind))


def _get(url: str, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download(remote: RemoteFile, dest_root: Path) -> tuple[Path, bool]:
    """Download one file; skip if present. Returns (path, downloaded)."""
    target = dest_root / remote.calc_date / remote.name
    if target.exists() and target.stat().st_size > 0:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(_get(BASE_URL + remote.name, timeout=600))
    tmp.replace(target)  # atomic: a crashed run never leaves a truncated file under the real name
    return target, True


def select(files: list[RemoteFile], kinds: set[str], dates: str) -> list[RemoteFile]:
    wanted = [f for f in files if f.kind in kinds]
    if dates == "all":
        return wanted
    calc_dates = sorted({f.calc_date for f in wanted})
    if not calc_dates:
        return []
    target = calc_dates[-1] if dates == "latest" else dates
    return [f for f in wanted if f.calc_date == target]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    p.add_argument(
        "--date",
        default="latest",
        help="'latest' (default), 'all' (whole published window) or a calc date YYYYMMDD",
    )
    p.add_argument("--with-spreads", action="store_true", help="also fetch intercommodityspreads (~55 MB/day)")
    p.add_argument("--with-spanfile", action="store_true", help="also fetch ECC_SPANFILE xml.zip (~20 MB/day)")
    args = p.parse_args(argv)

    kinds = set(DEFAULT_KINDS)
    if args.with_spreads:
        kinds.add("intercommodityspreads")
    if args.with_spanfile:
        kinds.add("spanfile")

    files = select(parse_index(_get(INDEX_URL).decode("utf-8", "replace")), kinds, args.date)
    if not files:
        print(f"No matching files on {INDEX_URL} for date={args.date}", file=sys.stderr)
        return 1
    for f in files:
        path, fetched = download(f, args.dest)
        print(f"{'downloaded' if fetched else 'exists    '}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
