"""CSV and JSON report writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.os_collector import OSCollectionRecord
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord

CSV_FIELDS = [
    "cluster",
    "host",
    "address",
    "collected_at",
    "status",
    "error",
    "ssh_returncode",
    "hostname",
    "uptime",
    "filesystems_json",
    "free_mb_json",
    "cpu_json",
    "meminfo_json",
]


def write_os_csv(records: Iterable[OSCollectionRecord], output_dir: Path) -> Path:
    """Write OS collection records to output/os_inventory.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "os_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path


def write_os_json(records: Iterable[OSCollectionRecord], output_dir: Path) -> Path:
    """Write OS collection records to output/os_inventory.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "os_inventory.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in records], json_file, indent=2)
        json_file.write("\n")
    return json_path


DB_CSV_FIELDS = [
    "cluster","host","address","collected_at","status","error","ssh_returncode","hostname","date","gi_version","oratab","pmon_processes_json","databases_json","srvctl_config_json","srvctl_status_json","crsctl_stat_res_t","oracle_home_candidates_json",
]

def write_db_inventory_csv(records: Iterable[DBInventoryRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DB_CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path

def write_db_inventory_json(records: Iterable[DBInventoryRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_inventory.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in records], json_file, indent=2)
        json_file.write("\n")
    return json_path


ASM_CSV_FIELDS = [
    "cluster", "host", "address", "record_type", "collected_at", "diskgroup_name", "state", "type",
    "total_mb", "free_mb", "usable_file_mb", "free_pct", "usable_pct", "used_pct", "warning_level",
    "asm_collection_status", "asm_collection_error", "asm_error", "grid_home", "grid_owner", "asm_sid",
    "asmcmd_path", "asm_command", "asm_env_stdout", "asm_returncode", "asmcmd_stdout", "asmcmd_stderr",
    "sqlplus_stdout", "sqlplus_stderr", "sqlplus_returncode",
]

ASM_METADATA_FIELDS = [
    "cluster", "host", "address", "collected_at", "asm_collection_status", "grid_home", "grid_owner",
    "asm_sid", "asmcmd_path", "asm_command", "asm_returncode", "asmcmd_stdout", "asmcmd_stderr",
]

ASM_SUMMARY_FIELDS = ["cluster", "diskgroup", "total_gb", "free_gb", "used_pct", "warning_level"]

def write_asm_diskgroups_csv(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_diskgroups.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ASM_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in _diskgroup_records(records):
            writer.writerow(record.to_csv_row())
    return csv_path

def write_asm_diskgroups_json(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_diskgroups.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in _diskgroup_records(records)], json_file, indent=2)
        json_file.write("\n")
    return json_path

def write_asm_metadata_csv(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_metadata.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ASM_METADATA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in _metadata_records(records):
            writer.writerow(record.to_csv_row())
    return csv_path

def write_asm_metadata_json(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_metadata.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in _metadata_records(records)], json_file, indent=2)
        json_file.write("\n")
    return json_path

def write_asm_summary_csv(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_summary.csv"
    rows = _asm_summary_rows(records)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ASM_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path

def _diskgroup_records(records: Iterable[ASMDiskgroupRecord]) -> list[ASMDiskgroupRecord]:
    return [record for record in records if record.record_type != "host_metadata"]

def _metadata_records(records: Iterable[ASMDiskgroupRecord]) -> list[ASMDiskgroupRecord]:
    return [record for record in records if record.record_type == "host_metadata"]

def _asm_summary_rows(records: Iterable[ASMDiskgroupRecord]) -> list[dict[str, object]]:
    by_diskgroup: dict[tuple[str, str], ASMDiskgroupRecord] = {}
    for record in records:
        if record.record_type == "host_metadata" or not record.diskgroup_name or record.total_mb <= 0:
            continue
        by_diskgroup.setdefault((record.cluster, record.diskgroup_name), record)
    rows = []
    for (cluster, diskgroup), record in sorted(by_diskgroup.items()):
        rows.append(
            {
                "cluster": cluster,
                "diskgroup": diskgroup,
                "total_gb": _mb_to_gb(record.total_mb),
                "free_gb": _mb_to_gb(record.free_mb),
                "used_pct": record.used_pct,
                "warning_level": record.warning_level,
            }
        )
    return rows

def _mb_to_gb(value: int) -> float:
    return round(value / 1024, 2)
