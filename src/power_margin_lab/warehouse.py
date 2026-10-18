"""DuckDB warehouse helpers (data/warehouse.duckdb, gitignored)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def connect(path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def write(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
    con.unregister("_df")


def read(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    return con.execute(f"SELECT * FROM {name}").df()


def has(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    q = "SELECT count(*) FROM information_schema.tables WHERE table_name = ?"
    return con.execute(q, [name]).fetchone()[0] > 0
