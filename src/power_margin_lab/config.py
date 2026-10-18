"""Paths and YAML configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Paths:
    data: Path
    reports: Path
    config: Path

    @property
    def raw_ecc(self) -> Path:
        return self.data / "raw" / "ecc"

    @property
    def raw_smard(self) -> Path:
        return self.data / "raw" / "smard"

    @property
    def interim(self) -> Path:
        return self.data / "interim"

    @property
    def warehouse(self) -> Path:
        return self.data / "warehouse.duckdb"


def get_paths(data: str | Path | None = None, reports: str | Path | None = None,
              config: str | Path | None = None) -> Paths:
    """Resolve paths. Arguments override the env vars PML_DATA_DIR, PML_REPORTS_DIR and
    PML_CONFIG_DIR, which override the repository defaults."""
    return Paths(
        data=Path(data or os.environ.get("PML_DATA_DIR", ROOT / "data")),
        reports=Path(reports or os.environ.get("PML_REPORTS_DIR", ROOT / "reports")),
        config=Path(config or os.environ.get("PML_CONFIG_DIR", ROOT / "config")),
    )


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_model_config(paths: Paths) -> dict:
    return load_yaml(paths.config / "model.yml")


def load_portfolios(paths: Paths) -> dict:
    return load_yaml(paths.config / "portfolios.yml")["portfolios"]
