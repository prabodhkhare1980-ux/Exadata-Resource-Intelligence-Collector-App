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

    normalized = _build_normalized(results)
    (json_dir / "normalized_hosts.json").write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(csv_dir / "filesystem_usage.csv", results.get("filesystem", []))
    _write_csv(csv_dir / "cpu_inventory.csv", results.get("cpu_memory", []))
    _write_csv(
        csv_dir / "db_inventory.csv",
        [
            {
                "environment": row.get("environment"),
                "cluster": row.get("cluster"),
                "host": row.get("host"),
                "address": row.get("address"),
                "db_unique_name": db.get("db_unique_name"),
                "config_raw": db.get("config_raw"),
                "status_raw": db.get("status_raw"),
            }
            for row in results.get("grid_env_detector", [])
            for db in row.get("srvctl_databases", [])
        ],
    )
    _write_csv(
        csv_dir / "pmon_instances.csv",
        [
            {
                "environment": row.get("environment"),
                "cluster": row.get("cluster"),
                "host": row.get("host"),
                "db_unique_name": inst.get("mapped_db_unique_name"),
                "os_user": inst.get("os_user"),
                "pid": inst.get("pid"),
                "sid": inst.get("sid"),
                "mapping_source": inst.get("mapping_source"),
            }
            for row in results.get("grid_env_detector", [])
            for inst in row.get("pmon_instances", [])
        ],
    )
    _write_csv(csv_dir / "hugepages.csv", [])

    asm_rows = results.get("asm_diskgroups", [])
    (output_dir / "asm_diskgroups.json").write_text(
        json.dumps(asm_rows, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(output_dir / "asm_diskgroups.csv", asm_rows)


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


def _build_normalized(results: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_host: dict[tuple[str, str], dict[str, Any]] = {}
    for row in results.get("os", []):
        key = (str(row.get("cluster", "")), str(row.get("host", "")))
        by_host[key] = {"cluster": key[0], "host": key[1], "os": row, "filesystem": [], "memory": {}, "cpu": {}, "hugepages": {}, "oracle_inventory": {}, "raw": {}}
    for row in results.get("filesystem", []):
        key = (str(row.get("cluster", "")), str(row.get("host", "")))
        by_host.setdefault(key, {"cluster": key[0], "host": key[1], "os": {}, "filesystem": [], "memory": {}, "cpu": {}, "hugepages": {}, "oracle_inventory": {}, "raw": {}})["filesystem"].append(row)
    for row in results.get("cpu_memory", []):
        key = (str(row.get("cluster", "")), str(row.get("host", "")))
        target = by_host.setdefault(key, {"cluster": key[0], "host": key[1], "os": {}, "filesystem": [], "memory": {}, "cpu": {}, "hugepages": {}, "oracle_inventory": {}, "raw": {}})
        target["cpu"] = {k: row.get(k) for k in ("cpu_count", "load_1m", "load_5m", "load_15m")}
        target["memory"] = {k: row.get(k) for k in ("mem_total_mb", "mem_used_mb", "mem_free_mb", "mem_available_mb", "swap_total_mb", "swap_used_mb")}
    for row in results.get("grid_env_detector", []):
        key = (str(row.get("cluster", "")), str(row.get("host", "")))
        by_host.setdefault(key, {"cluster": key[0], "host": key[1], "os": {}, "filesystem": [], "memory": {}, "cpu": {}, "hugepages": {}, "oracle_inventory": {}, "raw": {}})["oracle_inventory"] = row
    return list(by_host.values())
