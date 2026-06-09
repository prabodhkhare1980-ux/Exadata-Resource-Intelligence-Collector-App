"""Tests for the Dash data_loader service."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.data_loader import (  # noqa: E402
    list_output_files,
    preferred_output_path,
    read_file,
    read_output,
    read_output_with_path,
)


def test_read_output_missing_file_returns_empty(tmp_path: Path) -> None:
    result = read_output("does_not_exist", output_dir=tmp_path)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_preferred_output_path_prefers_json(tmp_path: Path) -> None:
    (tmp_path / "stem.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "stem.json").write_text("[{\"a\": 1}]", encoding="utf-8")
    chosen = preferred_output_path("stem", output_dir=tmp_path)
    assert chosen is not None
    assert chosen.suffix == ".json"


def test_read_output_json_list(tmp_path: Path) -> None:
    payload = [{"cluster": "c1", "value": 10}, {"cluster": "c2", "value": 20}]
    (tmp_path / "asm_diskgroups.json").write_text(json.dumps(payload), encoding="utf-8")
    df = read_output("asm_diskgroups", output_dir=tmp_path)
    assert set(df.columns) == {"cluster", "value"}
    assert df["value"].tolist() == [10, 20]


def test_read_output_csv(tmp_path: Path) -> None:
    (tmp_path / "stem.csv").write_text("cluster,value\nc1,5\nc2,9\n", encoding="utf-8")
    df = read_output("stem", output_dir=tmp_path)
    assert df["value"].tolist() == [5, 9]


def test_read_output_with_path_returns_path(tmp_path: Path) -> None:
    (tmp_path / "stem.json").write_text("[]", encoding="utf-8")
    df, path = read_output_with_path("stem", output_dir=tmp_path)
    assert path is not None
    assert path.name == "stem.json"
    assert df.empty


def test_list_output_files_excludes_unknown(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b.csv").write_text("x,y\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("ignore", encoding="utf-8")
    names = {path.name for path in list_output_files(tmp_path)}
    assert names == {"a.json", "b.csv"}


def test_read_file_malformed_json_raises(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_file(target)


def test_read_output_swallows_broken_json(tmp_path: Path) -> None:
    (tmp_path / "stem.json").write_text("{not json", encoding="utf-8")
    df = read_output("stem", output_dir=tmp_path)
    assert df.empty
