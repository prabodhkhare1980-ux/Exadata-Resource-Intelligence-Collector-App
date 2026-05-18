"""Local CSV and JSON output writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .collectors import CollectionResult


def write_results(output_dir: Path, results: dict[str, list[dict[str, Any]]], errors: list[dict[str, Any]]) -> None:
    """Write collector results to CSV and JSON files under output_dir."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_dir = output_dir / "json"
    csv_dir = output_dir / "csv"
    json_dir.mkdir(exist_ok=True)
    csv_dir.mkdir(exist_ok=True)

    for name, rows in results.items():
        (json_dir / f"{name}.json").write_text(
            json.dumps(rows, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(csv_dir / f"{name}.csv", rows)

    (json_dir / "errors.json").write_text(
        json.dumps(errors, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_dir / "errors.csv", errors)


def merge_results(results: list[CollectionResult]) -> dict[str, list[dict[str, Any]]]:
    """Group collection result rows by collector name."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result.name, []).extend(result.rows)
    return grouped


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not fieldnames:
            handle.write("")
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
