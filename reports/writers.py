"""CSV and JSON report writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.os_collector import OSCollectionRecord
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.hugepages_collector import HugePagesRecord

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
    "total_mb", "free_mb", "usable_file_mb", "total_tb", "free_tb", "usable_tb", "free_pct",
    "usable_pct", "used_pct", "warning_level", "asm_collection_status", "grid_home", "grid_owner",
    "asm_sid", "asmcmd_path",
]

ASM_DEBUG_FIELDS = [
    "asm_command", "asm_env_stdout", "asm_returncode", "asmcmd_stdout", "asmcmd_stderr",
    "sqlplus_stdout", "sqlplus_stderr", "sqlplus_returncode",
]

ASM_METADATA_FIELDS = [
    "cluster", "host", "address", "collected_at", "asm_collection_status", "grid_home", "grid_owner",
    "asm_sid", "asmcmd_path", "asm_command", "asm_returncode", "asmcmd_stdout", "asmcmd_stderr",
]

ASM_SUMMARY_FIELDS = [
    "cluster", "diskgroup_name", "type", "total_tb", "free_tb", "usable_tb", "used_pct",
    "free_pct", "usable_pct", "warning_level", "sample_host", "collected_at",
]

HUGEPAGES_FIELDS = [
    "cluster", "host", "address", "collected_at", "hugepages_total", "hugepages_free",
    "hugepages_rsvd", "hugepages_surp", "hugepagesize_kb", "hugetlb_kb", "hugepages_used",
    "hugepages_used_pct", "hugepages_free_pct", "warning_level", "collection_status",
    "collection_error",
]

def write_asm_diskgroups_csv(records: Iterable[ASMDiskgroupRecord], output_dir: Path, *, include_debug: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_diskgroups.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=_asm_csv_fields(include_debug), extrasaction="ignore")
        writer.writeheader()
        for record in _diskgroup_records(records):
            writer.writerow(record.to_csv_row(include_debug=include_debug))
    return csv_path

def write_asm_diskgroups_json(records: Iterable[ASMDiskgroupRecord], output_dir: Path, *, include_debug: bool = False) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_diskgroups.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict(include_debug=include_debug) for record in _diskgroup_records(records)], json_file, indent=2)
        json_file.write("\n")
    return json_path

def write_asm_metadata_csv(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_metadata.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ASM_METADATA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in _metadata_records(records):
            writer.writerow(record.to_csv_row(include_debug=True))
    return csv_path

def write_asm_metadata_json(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_metadata.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict(include_debug=True) for record in _metadata_records(records)], json_file, indent=2)
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


def write_asm_summary_json(records: Iterable[ASMDiskgroupRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_summary.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(_asm_summary_rows(records), json_file, indent=2)
        json_file.write("\n")
    return json_path


def write_hugepages_csv(records: Iterable[HugePagesRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "hugepages.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=HUGEPAGES_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path


def write_hugepages_json(records: Iterable[HugePagesRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "hugepages.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in records], json_file, indent=2)
        json_file.write("\n")
    return json_path

def _diskgroup_records(records: Iterable[ASMDiskgroupRecord]) -> list[ASMDiskgroupRecord]:
    return [record for record in records if record.record_type != "host_metadata"]

def _metadata_records(records: Iterable[ASMDiskgroupRecord]) -> list[ASMDiskgroupRecord]:
    return [record for record in records if record.record_type == "host_metadata"]

def _asm_summary_rows(records: Iterable[ASMDiskgroupRecord]) -> list[dict[str, object]]:
    by_diskgroup: dict[tuple[str, str], ASMDiskgroupRecord] = {}
    for record in records:
        if record.record_type == "host_metadata" or record.asm_collection_status != "success" or not record.diskgroup_name:
            continue
        by_diskgroup.setdefault((record.cluster, record.diskgroup_name), record)
    rows = []
    for (cluster, diskgroup), record in sorted(by_diskgroup.items()):
        rows.append(
            {
                "cluster": cluster,
                "diskgroup_name": diskgroup,
                "type": record.type,
                "total_tb": _mb_to_tb(record.total_mb),
                "free_tb": _mb_to_tb(record.free_mb),
                "usable_tb": _mb_to_tb(record.usable_file_mb),
                "used_pct": record.used_pct,
                "free_pct": record.free_pct,
                "usable_pct": record.usable_pct,
                "warning_level": record.warning_level,
                "sample_host": record.host,
                "collected_at": record.collected_at,
            }
        )
    return rows


def _asm_csv_fields(include_debug: bool) -> list[str]:
    if include_debug:
        return [*ASM_CSV_FIELDS, *ASM_DEBUG_FIELDS]
    return ASM_CSV_FIELDS


def _mb_to_tb(value: int) -> float:
    return round(value / 1024 / 1024, 2)
