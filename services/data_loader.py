"""Local-only loader for collector output files.

The Dash dashboard reads JSON or CSV files written to ``output/`` by the
collectors. It never imports collector runtime code, never opens SSH
connections, and never executes remote commands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

OUTPUT_DIR = Path("output")


def preferred_output_path(stem: str, output_dir: Path | None = None) -> Path | None:
    """Return the JSON path if present, otherwise CSV, otherwise None."""

    base = output_dir or OUTPUT_DIR
    for suffix in (".json", ".csv"):
        candidate = base / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def read_file(path: Path) -> pd.DataFrame:
    """Read a JSON or CSV file into a dataframe."""

    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        return pd.json_normalize(payload)
    return pd.DataFrame({"value": [payload]})


def read_output(stem: str, output_dir: Path | None = None) -> pd.DataFrame:
    """Read a collector output stem into a dataframe, or empty if missing."""

    path = preferred_output_path(stem, output_dir=output_dir)
    if path is None:
        return pd.DataFrame()
    try:
        return read_file(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return pd.DataFrame()


def read_output_with_path(
    stem: str, output_dir: Path | None = None
) -> tuple[pd.DataFrame, Path | None]:
    """Read a collector output stem and return (dataframe, path-or-None)."""

    path = preferred_output_path(stem, output_dir=output_dir)
    if path is None:
        return pd.DataFrame(), None
    try:
        return read_file(path), path
    except (OSError, ValueError, json.JSONDecodeError):
        return pd.DataFrame(), path


def list_output_files(output_dir: Path | None = None) -> list[Path]:
    """List JSON/CSV files in the output directory for the raw explorer."""

    base = output_dir or OUTPUT_DIR
    if not base.exists():
        return []
    files: list[Path] = []
    for suffix in (".json", ".csv"):
        files.extend(sorted(base.glob(f"*{suffix}")))
    return files


def read_raw_json(path: Path) -> Any:
    """Read JSON payload for the raw explorer."""

    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
