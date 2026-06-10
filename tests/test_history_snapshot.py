"""Tests for the historical snapshot retention service."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.history import (  # noqa: E402
    list_snapshots,
    read_history,
    snapshot_outputs,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_snapshot_appends_each_run(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    db_path = tmp_path / "history.sqlite"

    _write_json(
        output_dir / "asm_diskgroups.json",
        [{"cluster": "c1", "diskgroup_name": "DATA", "total_tb": 10, "free_tb": 5}],
    )
    _write_json(
        output_dir / "db_resource_details.json",
        [{"cluster": "c1", "db_name": "ORCL", "db_size_gb": 1000}],
    )

    first = snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-10T00:00:00Z"
    )
    assert first == {"asm_diskgroups": 1, "db_resource_details": 1}

    # Mutate one of the source outputs and snapshot again.
    _write_json(
        output_dir / "asm_diskgroups.json",
        [
            {"cluster": "c1", "diskgroup_name": "DATA", "total_tb": 10, "free_tb": 4},
            {"cluster": "c1", "diskgroup_name": "RECO", "total_tb": 5, "free_tb": 2},
        ],
    )
    second = snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-11T00:00:00Z"
    )
    assert second["asm_diskgroups"] == 2

    history = read_history("asm_diskgroups", db_path=db_path)
    # 1 row from the first snapshot + 2 from the second.
    assert len(history) == 3
    assert sorted(history["snapshot_at"].unique().tolist()) == [
        "2026-06-10T00:00:00Z",
        "2026-06-11T00:00:00Z",
    ]


def test_snapshot_records_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    db_path = tmp_path / "history.sqlite"
    _write_json(
        output_dir / "hugepages.json",
        [{"Cluster": "c1", "Host": "h1", "HP_Total": 100}],
    )

    snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-10T00:00:00Z"
    )
    meta = list_snapshots(db_path=db_path)
    assert not meta.empty
    row = meta.iloc[0]
    assert row["stem"] == "hugepages"
    assert row["rows"] == 1
    assert row["snapshot_at"] == "2026-06-10T00:00:00Z"


def test_snapshot_skips_missing_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    db_path = tmp_path / "history.sqlite"

    result = snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-10T00:00:00Z"
    )
    assert result == {}
    # The DB file may or may not exist; if it does, it should at least be valid.
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
        assert "_snapshots" in tables


def test_snapshot_handles_new_columns_in_subsequent_run(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    db_path = tmp_path / "history.sqlite"

    _write_json(
        output_dir / "asm_diskgroups.json",
        [{"cluster": "c1", "diskgroup_name": "DATA", "total_tb": 10}],
    )
    snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-10T00:00:00Z"
    )

    # A later run adds a new column the original table didn't have.
    _write_json(
        output_dir / "asm_diskgroups.json",
        [
            {
                "cluster": "c1",
                "diskgroup_name": "DATA",
                "total_tb": 10,
                "usable_tb": 6,  # new column
            }
        ],
    )
    snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-11T00:00:00Z"
    )
    history = read_history("asm_diskgroups", db_path=db_path)
    assert "usable_tb" in history.columns
    # First-run row has NaN for the new column.
    first = history[history["snapshot_at"] == "2026-06-10T00:00:00Z"].iloc[0]
    assert pd.isna(first["usable_tb"])
    second = history[history["snapshot_at"] == "2026-06-11T00:00:00Z"].iloc[0]
    assert float(second["usable_tb"]) == 6.0


def test_read_history_since_filters_by_snapshot_at(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    db_path = tmp_path / "history.sqlite"
    _write_json(
        output_dir / "asm_diskgroups.json",
        [{"cluster": "c1", "diskgroup_name": "DATA", "total_tb": 10}],
    )
    snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-10T00:00:00Z"
    )
    snapshot_outputs(
        output_dir=output_dir, db_path=db_path, snapshot_at="2026-06-11T00:00:00Z"
    )
    recent = read_history(
        "asm_diskgroups", db_path=db_path, since="2026-06-11T00:00:00Z"
    )
    assert len(recent) == 1
    assert recent.iloc[0]["snapshot_at"] == "2026-06-11T00:00:00Z"
