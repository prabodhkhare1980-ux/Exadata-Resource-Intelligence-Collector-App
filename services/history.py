"""Historical snapshot retention for collector outputs.

The collectors overwrite ``output/`` on every run, so the dashboard sees
only the latest snapshot. This module appends each run to a local SQLite
store (default ``output/history.sqlite``) keyed by ``snapshot_at`` plus
each output's natural identity columns. That makes growth-rate, trend,
and days-to-full analytics possible.

Design notes
------------
- One row per (collector output stem, snapshot_at, ...identity).
- The store is intentionally schema-flexible: every dataframe is written
  with whatever columns it had at snapshot time, plus a ``snapshot_at``
  column. SQLite stores everything as TEXT/REAL/INTEGER; pandas handles
  the marshalling via ``df.to_sql``.
- This is append-only. There is no schema migration step — adding a new
  column to a collector output causes ``df.to_sql`` to add it to the
  table on the next snapshot (via ``if_exists='append'`` with the union
  of columns, which pandas + sqlalchemy handle naturally; for the
  stdlib ``sqlite3`` connection we use here we apply the union ourselves
  before writing).
- Read-only consumers should never write to this store from the
  dashboard process. The dashboard may *read* aggregates from it in
  later phases.

CLI
---
::

    python -m services.history snapshot
    python -m services.history snapshot --output-dir output/ --db output/history.sqlite
    python -m services.history list-snapshots
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from services.data_loader import read_output

# Stems persisted into history. Keep the list explicit so we don't
# accidentally snapshot ephemeral side outputs (errors files, etc.).
HISTORY_STEMS: tuple[str, ...] = (
    "asm_diskgroups",
    "hugepages",
    "os_inventory",
    "db_resource_details",
    "db_performance",
    "db_memory_history",
    "db_memory_history_summary",
    "db_memory_cluster_summary",
    "version_inventory",
    "health_summary",
)

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_DB_PATH = DEFAULT_OUTPUT_DIR / "history.sqlite"
META_TABLE = "_snapshots"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {META_TABLE} (
            snapshot_at TEXT NOT NULL,
            stem        TEXT NOT NULL,
            rows        INTEGER NOT NULL,
            source_path TEXT,
            PRIMARY KEY (snapshot_at, stem)
        )
        """
    )


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return {row[1] for row in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _coerce_for_sqlite(df: pd.DataFrame) -> pd.DataFrame:
    """Cast list/dict cells to JSON strings so SQLite can store them."""

    out = df.copy()
    for column in out.columns:
        sample = next(
            (v for v in out[column].dropna().tolist() if not isinstance(v, (int, float, str, bool))),
            None,
        )
        if sample is None:
            continue
        out[column] = out[column].map(
            lambda v: json.dumps(v) if isinstance(v, (list, dict)) else v
        )
    return out


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, df: pd.DataFrame
) -> None:
    if not _table_exists(conn, table):
        return
    existing = _existing_columns(conn, table)
    for column in df.columns:
        if column not in existing:
            # All new columns added as TEXT; pandas widens as needed.
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" TEXT')


def snapshot_outputs(
    output_dir: Path | None = None,
    db_path: Path | None = None,
    stems: Iterable[str] | None = None,
    snapshot_at: str | None = None,
) -> dict[str, int]:
    """Append the current ``output/`` snapshot to the history SQLite store.

    Returns a mapping of stem → rows written. Stems with no current
    output file are skipped silently (not an error — they just weren't
    collected this run).
    """

    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    db_path = db_path or DEFAULT_DB_PATH
    stems = tuple(stems) if stems is not None else HISTORY_STEMS
    snapshot_at = snapshot_at or _now_iso()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    written: dict[str, int] = {}

    with sqlite3.connect(db_path) as conn:
        _ensure_meta_table(conn)
        for stem in stems:
            df = read_output(stem, output_dir=output_dir)
            if df is None or df.empty:
                continue
            df = _coerce_for_sqlite(df)
            df = df.assign(snapshot_at=snapshot_at)
            table = stem
            _add_missing_columns(conn, table, df)
            df.to_sql(table, conn, if_exists="append", index=False)
            conn.execute(
                f"INSERT OR REPLACE INTO {META_TABLE} "
                "(snapshot_at, stem, rows, source_path) VALUES (?, ?, ?, ?)",
                (snapshot_at, stem, int(len(df)), str(output_dir / f"{stem}")),
            )
            written[stem] = int(len(df))
        conn.commit()
    return written


def list_snapshots(db_path: Path | None = None) -> pd.DataFrame:
    """Return the metadata for all snapshots in the store."""

    db_path = db_path or DEFAULT_DB_PATH
    if not db_path.exists():
        return pd.DataFrame(columns=["snapshot_at", "stem", "rows", "source_path"])
    with sqlite3.connect(db_path) as conn:
        _ensure_meta_table(conn)
        return pd.read_sql_query(
            f"SELECT snapshot_at, stem, rows, source_path FROM {META_TABLE} "
            "ORDER BY snapshot_at DESC, stem",
            conn,
        )


def read_history(
    stem: str, db_path: Path | None = None, since: str | None = None
) -> pd.DataFrame:
    """Read all historical rows for ``stem`` from the store.

    ``since`` is an ISO timestamp string; if given, only snapshots with
    ``snapshot_at >= since`` are returned.
    """

    db_path = db_path or DEFAULT_DB_PATH
    if not db_path.exists():
        return pd.DataFrame()
    with sqlite3.connect(db_path) as conn:
        if not _table_exists(conn, stem):
            return pd.DataFrame()
        if since:
            return pd.read_sql_query(
                f'SELECT * FROM "{stem}" WHERE snapshot_at >= ? ORDER BY snapshot_at',
                conn,
                params=(since,),
            )
        return pd.read_sql_query(
            f'SELECT * FROM "{stem}" ORDER BY snapshot_at', conn
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m services.history",
        description="Append the current output/ snapshot to history.sqlite.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snap = subparsers.add_parser("snapshot", help="Append current outputs to history.")
    snap.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    snap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    snap.add_argument(
        "--snapshot-at",
        type=str,
        default=None,
        help="Override snapshot timestamp (ISO 8601); defaults to now (UTC).",
    )

    lst = subparsers.add_parser("list-snapshots", help="List recorded snapshots.")
    lst.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    args = parser.parse_args()
    if args.command == "snapshot":
        result = snapshot_outputs(
            output_dir=args.output_dir,
            db_path=args.db,
            snapshot_at=args.snapshot_at,
        )
        if not result:
            print(f"No outputs found under {args.output_dir} to snapshot.")
            return 1
        for stem, rows in result.items():
            print(f"snapshot wrote {rows:>6} rows  ->  {stem}")
        print(f"db: {args.db}")
        return 0
    if args.command == "list-snapshots":
        df = list_snapshots(db_path=args.db)
        if df.empty:
            print(f"No snapshots recorded at {args.db}.")
            return 0
        with pd.option_context("display.max_rows", 200, "display.width", 120):
            print(df.to_string(index=False))
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
