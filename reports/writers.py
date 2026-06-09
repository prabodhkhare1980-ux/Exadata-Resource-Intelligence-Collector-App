"""CSV and JSON report writers."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any, Iterable

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.os_collector import OSCollectionRecord
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.hugepages_collector import HugePagesRecord
from collectors.version_inventory_collector import VersionInventoryRecord
from collectors.db_performance_collector import (
    DBMemoryHistoryRecord,
    DBPerformanceRecord,
    DB_MEMORY_COLUMNS,
    DB_PERFORMANCE_COLUMNS,
)

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
    "cluster",
    "host",
    "address",
    "collected_at",
    "status",
    "error",
    "ssh_returncode",
    "hostname",
    "date",
    "gi_version",
    "oratab",
    "pmon_processes_json",
    "databases_json",
    "srvctl_config_json",
    "srvctl_status_json",
    "crsctl_stat_res_t",
    "oracle_home_candidates_json",
    "db_resource_details_json",
    "grid_home",
    "grid_owner",
    "srvctl_database_list_returncode",
    "srvctl_database_list_stderr",
    "db_resource_details_count",
    "collection_status",
    "collection_error",
]


def write_db_inventory_csv(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DB_CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path


DB_RESOURCE_SUCCESS_CSV_FIELDS = [
    "Cluster",
    "HOST_NAME",
    "DB_NAME",
    "DB_ROLE",
    "OPEN_MODE",
    "VERSION",
    "RAC_ENABLED",
    "INST_COUNT",
    "SGA_TARGET_GB",
    "PGA_AGGR_TARGET_GB",
    "SGA_MAX_SIZE_GB",
    "PGA_AGGR_LIMIT_GB",
    "PROCESSES",
    "CPU_COUNT",
    "DB_SIZE_GB",
    "USED_DB_SIZE_GB",
    "DB_USED_PCT",
    "db_unique_name",
    "oracle_home",
    "oracle_sid",
    "size_source",
    "Collected_At",
]

DB_RESOURCE_SUCCESS_JSON_FIELDS = [
    "cluster",
    "host",
    "address",
    "host_name",
    "db_name",
    "db_role",
    "open_mode",
    "version",
    "rac_enabled",
    "inst_count",
    "sga_target_gb",
    "pga_aggr_target_gb",
    "sga_max_size_gb",
    "pga_aggr_limit_gb",
    "processes",
    "cpu_count",
    "db_size_gb",
    "used_db_size_gb",
    "db_used_pct",
    "db_unique_name",
    "oracle_home",
    "oracle_sid",
    "size_source",
    "collection_status",
    "collection_error",
    "collected_at",
    "mapping_source",
]

DB_RESOURCE_ERROR_FIELDS = [
    "cluster",
    "host",
    "address",
    "db_unique_name",
    "oracle_home",
    "oracle_sid",
    "collection_status",
    "collection_error",
    "error_category",
    "sql_returncode",
    "sql_stdout",
    "sql_stderr",
    "collected_at",
    "mapping_source",
]


def write_db_resource_details_csv(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_resource_details.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_RESOURCE_SUCCESS_CSV_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(_db_resource_success_csv_rows(records))
    return csv_path


def write_db_resource_details_json(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_resource_details.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(_db_resource_success_json_rows(records), json_file, indent=2)
        json_file.write("\n")
    return json_path


def write_db_resource_details_errors_csv(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_resource_details_errors.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_RESOURCE_ERROR_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(_db_resource_error_rows(records))
    return csv_path


def write_db_resource_details_errors_json(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_resource_details_errors.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(_db_resource_error_rows(records), json_file, indent=2)
        json_file.write("\n")
    return json_path


def _db_resource_detail_rows(
    records: Iterable[DBInventoryRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.extend(dict(row) for row in record.db_resource_details)
    return rows


def _db_resource_success_csv_rows(
    records: Iterable[DBInventoryRecord],
) -> list[dict[str, object]]:
    return [
        _db_resource_success_csv_row(row)
        for row in _db_resource_detail_rows(records)
        if str(row.get("collection_status") or "").lower() == "success"
    ]


def _db_resource_success_json_rows(
    records: Iterable[DBInventoryRecord],
) -> list[dict[str, object]]:
    return [
        _db_resource_success_json_row(row)
        for row in _db_resource_detail_rows(records)
        if str(row.get("collection_status") or "").lower() == "success"
    ]


def _db_resource_error_rows(
    records: Iterable[DBInventoryRecord],
) -> list[dict[str, object]]:
    return [
        {
            field: _canonical_db_resource_row(row).get(field, "")
            for field in DB_RESOURCE_ERROR_FIELDS
        }
        for row in _db_resource_detail_rows(records)
        if str(row.get("collection_status") or "").lower() in {"skipped", "failed"}
    ]


def _db_resource_success_csv_row(row: dict[str, object]) -> dict[str, object]:
    used_pct = _db_used_pct(row)
    return {
        "Cluster": row.get("Cluster") or row.get("cluster") or "",
        "HOST_NAME": row.get("HOST_NAME") or row.get("host_name") or "",
        "DB_NAME": row.get("DB_NAME") or row.get("db_name") or "",
        "DB_ROLE": row.get("DB_ROLE") or row.get("db_role") or "",
        "OPEN_MODE": row.get("OPEN_MODE") or row.get("open_mode") or "",
        "VERSION": row.get("VERSION") or row.get("version") or "",
        "RAC_ENABLED": row.get("RAC_ENABLED") or row.get("rac_enabled") or "",
        "INST_COUNT": row.get("INST_COUNT") or row.get("inst_count") or "",
        "SGA_TARGET_GB": row.get("SGA_TARGET_GB") or row.get("sga_target_gb") or "",
        "PGA_AGGR_TARGET_GB": row.get("PGA_AGGR_TARGET_GB")
        or row.get("pga_aggr_target_gb")
        or "",
        "SGA_MAX_SIZE_GB": row.get("SGA_MAX_SIZE_GB")
        or row.get("sga_max_size_gb")
        or "",
        "PGA_AGGR_LIMIT_GB": row.get("PGA_AGGR_LIMIT_GB")
        or row.get("pga_aggr_limit_gb")
        or "",
        "PROCESSES": row.get("PROCESSES") or row.get("processes") or "",
        "CPU_COUNT": row.get("CPU_COUNT") or row.get("cpu_count") or "",
        "DB_SIZE_GB": row.get("DB_SIZE_GB") or row.get("db_size_gb") or "",
        "USED_DB_SIZE_GB": row.get("USED_DB_SIZE_GB")
        or row.get("used_db_size_gb")
        or "",
        "DB_USED_PCT": used_pct,
        "db_unique_name": row.get("db_unique_name") or "",
        "oracle_home": row.get("oracle_home") or "",
        "oracle_sid": row.get("oracle_sid") or "",
        "size_source": row.get("size_source") or "",
        "Collected_At": row.get("Collected_At") or row.get("collected_at") or "",
    }


def _db_resource_success_json_row(row: dict[str, object]) -> dict[str, object]:
    canonical = _canonical_db_resource_row(row)
    return {
        field: canonical.get(field, "") for field in DB_RESOURCE_SUCCESS_JSON_FIELDS
    }


def _canonical_db_resource_row(row: dict[str, object]) -> dict[str, object]:
    canonical = {
        "cluster": row.get("cluster") or row.get("Cluster") or "",
        "host": row.get("host") or "",
        "address": row.get("address") or "",
        "host_name": row.get("host_name") or row.get("HOST_NAME") or "",
        "db_name": row.get("db_name") or row.get("DB_NAME") or "",
        "db_role": row.get("db_role") or row.get("DB_ROLE") or "",
        "open_mode": row.get("open_mode") or row.get("OPEN_MODE") or "",
        "version": row.get("version") or row.get("VERSION") or "",
        "rac_enabled": row.get("rac_enabled") or row.get("RAC_ENABLED") or "",
        "inst_count": row.get("inst_count") or row.get("INST_COUNT") or "",
        "sga_target_gb": row.get("sga_target_gb") or row.get("SGA_TARGET_GB") or "",
        "pga_aggr_target_gb": row.get("pga_aggr_target_gb")
        or row.get("PGA_AGGR_TARGET_GB")
        or "",
        "sga_max_size_gb": row.get("sga_max_size_gb")
        or row.get("SGA_MAX_SIZE_GB")
        or "",
        "pga_aggr_limit_gb": row.get("pga_aggr_limit_gb")
        or row.get("PGA_AGGR_LIMIT_GB")
        or "",
        "processes": row.get("processes") or row.get("PROCESSES") or "",
        "cpu_count": row.get("cpu_count") or row.get("CPU_COUNT") or "",
        "db_size_gb": row.get("db_size_gb") or row.get("DB_SIZE_GB") or "",
        "used_db_size_gb": row.get("used_db_size_gb")
        or row.get("USED_DB_SIZE_GB")
        or "",
        "db_used_pct": _db_used_pct(row),
        "db_unique_name": row.get("db_unique_name") or "",
        "oracle_home": row.get("oracle_home") or "",
        "oracle_sid": row.get("oracle_sid") or "",
        "size_source": row.get("size_source") or "",
        "collection_status": row.get("collection_status") or "",
        "collection_error": row.get("collection_error") or "",
        "error_category": row.get("error_category") or "",
        "sql_returncode": row.get("sql_returncode") or "",
        "sql_stdout": row.get("sql_stdout") or "",
        "sql_stderr": row.get("sql_stderr") or "",
        "collected_at": row.get("collected_at") or row.get("Collected_At") or "",
        "mapping_source": row.get("mapping_source") or "",
    }
    return canonical


def _db_used_pct(row: dict[str, object]) -> object:
    size = _optional_float(row.get("DB_SIZE_GB") or row.get("db_size_gb"))
    used = _optional_float(row.get("USED_DB_SIZE_GB") or row.get("used_db_size_gb"))
    if size in (None, 0) or used is None:
        return ""
    return round((used / size) * 100, 2)


def _optional_float(value: object) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def write_db_inventory_json(
    records: Iterable[DBInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_inventory.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in records], json_file, indent=2)
        json_file.write("\n")
    return json_path


ASM_CSV_FIELDS = [
    "cluster",
    "host",
    "address",
    "record_type",
    "collected_at",
    "diskgroup_name",
    "state",
    "type",
    "total_mb",
    "free_mb",
    "usable_file_mb",
    "total_tb",
    "free_tb",
    "usable_tb",
    "free_pct",
    "usable_pct",
    "used_pct",
    "warning_level",
    "asm_collection_status",
    "grid_home",
    "grid_owner",
    "asm_sid",
    "asmcmd_path",
]

ASM_DEBUG_FIELDS = [
    "asm_command",
    "asm_env_stdout",
    "asm_returncode",
    "asmcmd_stdout",
    "asmcmd_stderr",
    "sqlplus_stdout",
    "sqlplus_stderr",
    "sqlplus_returncode",
]

ASM_METADATA_FIELDS = [
    "cluster",
    "host",
    "address",
    "collected_at",
    "asm_collection_status",
    "grid_home",
    "grid_owner",
    "asm_sid",
    "asmcmd_path",
    "asm_command",
    "asm_returncode",
    "asmcmd_stdout",
    "asmcmd_stderr",
]

ASM_SUMMARY_FIELDS = [
    "cluster",
    "diskgroup_name",
    "type",
    "total_tb",
    "free_tb",
    "usable_tb",
    "used_pct",
    "free_pct",
    "usable_pct",
    "warning_level",
    "sample_host",
    "collected_at",
]

HUGEPAGES_FIELDS = [
    "Cluster",
    "Host",
    "MemTotal",
    "HP_Size_KB",
    "HP_Total",
    "HP_Free",
    "HP_Rsvd",
    "HP_Surp",
    "HP_Used",
    "HP_Used_GB",
    "HP_Total_GB",
    "HP_Pct_of_MemTotal",
    "THP_Status",
    "Timestamp",
]

VERSION_INVENTORY_FIELDS = [
    "cluster",
    "host",
    "address",
    "collected_at",
    "collection_status",
    "collection_error",
    "ssh_returncode",
    "kernel_version",
    "uptrack_kernel_version",
    "image_kernel_version",
    "image_version",
    "exadata_software_version",
    "image_activated",
    "image_status",
    "node_type",
    "system_partition_device",
    "imageinfo_path",
    "gi_active_version",
    "gi_software_patch_level",
    "gi_release_version",
    "gi_release_patch_level",
    "gi_release_patch_string",
    "gi_release_patch_list",
    "imageinfo_json",
]

VERSION_SUMMARY_FIELDS = [
    "cluster",
    "host",
    "image_version",
    "exadata_software_version",
    "gi_release_patch_string",
    "gi_release_version",
    "image_status",
]

HEALTH_SUMMARY_FIELDS = [
    "cluster",
    "host",
    "category",
    "object_name",
    "metric",
    "value",
    "warning_level",
    "recommendation",
    "details",
    "collected_at",
]


def write_asm_diskgroups_csv(
    diskgroup_records: Iterable[ASMDiskgroupRecord],
    output_dir: Path,
    *,
    include_debug: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_diskgroups.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=_asm_csv_fields(include_debug), extrasaction="ignore"
        )
        writer.writeheader()
        for record in diskgroup_records:
            writer.writerow(record.to_csv_row(include_debug=include_debug))
    return csv_path


def write_asm_diskgroups_json(
    diskgroup_records: Iterable[ASMDiskgroupRecord],
    output_dir: Path,
    *,
    include_debug: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_diskgroups.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                record.to_json_dict(include_debug=include_debug)
                for record in diskgroup_records
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def write_asm_metadata_csv(
    metadata_records: Iterable[ASMDiskgroupRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_metadata.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=ASM_METADATA_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in metadata_records:
            writer.writerow(record.to_csv_row(include_debug=True))
    return csv_path


def write_asm_metadata_json(
    metadata_records: Iterable[ASMDiskgroupRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "asm_metadata.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                record.to_json_dict(include_debug=True)
                for record in metadata_records
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def write_asm_summary_csv(
    records: Iterable[ASMDiskgroupRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "asm_summary.csv"
    rows = _asm_summary_rows(records)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ASM_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def write_asm_summary_json(
    records: Iterable[ASMDiskgroupRecord], output_dir: Path
) -> Path:
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
        writer = csv.DictWriter(
            csv_file, fieldnames=HUGEPAGES_FIELDS, extrasaction="ignore"
        )
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


def write_version_inventory_csv(
    records: Iterable[VersionInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "version_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=VERSION_INVENTORY_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path


def write_version_inventory_json(
    records: Iterable[VersionInventoryRecord],
    output_dir: Path,
    *,
    include_debug: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "version_inventory.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [record.to_json_dict(include_debug=include_debug) for record in records],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def write_version_summary_csv(
    records: Iterable[VersionInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "version_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=VERSION_SUMMARY_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in records:
            writer.writerow(_version_summary_row(record))
    return csv_path


def write_version_summary_json(
    records: Iterable[VersionInventoryRecord], output_dir: Path
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "version_summary.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [_version_summary_row(record) for record in records], json_file, indent=2
        )
        json_file.write("\n")
    return json_path


def _version_summary_row(record: VersionInventoryRecord) -> dict[str, object]:
    return {field: getattr(record, field) for field in VERSION_SUMMARY_FIELDS}


DB_PERFORMANCE_ERROR_COLUMNS = [
    *DB_PERFORMANCE_COLUMNS,
    "oracle_home",
    "sql_returncode",
    "sql_stdout",
    "sql_stderr",
]
DB_MEMORY_ERROR_COLUMNS = [
    *DB_MEMORY_COLUMNS,
    "oracle_home",
    "sql_returncode",
    "sql_stdout",
    "sql_stderr",
]


def write_db_performance_csv(
    records: Iterable[DBPerformanceRecord], output_dir: Path
) -> Path:
    """Write successful DB CPU/IOPS AWR history to output/db_performance.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_performance.csv"
    success_records = _dedupe_db_history_success(records)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_PERFORMANCE_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in success_records:
            writer.writerow(_db_history_success_row(record, DB_PERFORMANCE_COLUMNS))
    return csv_path


def write_db_performance_json(
    records: Iterable[DBPerformanceRecord], output_dir: Path
) -> Path:
    """Write successful DB CPU/IOPS AWR history to output/db_performance.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_performance.json"
    success_records = _dedupe_db_history_success(records)
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                _db_history_success_row(record, DB_PERFORMANCE_COLUMNS)
                for record in success_records
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def write_db_performance_errors_csv(
    records: Iterable[DBPerformanceRecord], output_dir: Path
) -> Path:
    """Write failed DB CPU/IOPS AWR collection rows to output/db_performance_errors.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_performance_errors.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_PERFORMANCE_ERROR_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in _db_history_error_records(records):
            writer.writerow(_db_history_error_row(record, DB_PERFORMANCE_ERROR_COLUMNS))
    return csv_path


def write_db_performance_errors_json(
    records: Iterable[DBPerformanceRecord], output_dir: Path
) -> Path:
    """Write failed DB CPU/IOPS AWR collection rows to output/db_performance_errors.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_performance_errors.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                _db_history_error_row(record, DB_PERFORMANCE_ERROR_COLUMNS)
                for record in _db_history_error_records(records)
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def write_db_memory_history_csv(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write successful DB SGA/PGA AWR history to output/db_memory_history.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_memory_history.csv"
    success_records = _dedupe_db_history_success(records)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_MEMORY_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in success_records:
            writer.writerow(_db_history_success_row(record, DB_MEMORY_COLUMNS))
    return csv_path


def write_db_memory_history_json(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write successful DB SGA/PGA AWR history to output/db_memory_history.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_memory_history.json"
    success_records = _dedupe_db_history_success(records)
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                _db_history_success_row(record, DB_MEMORY_COLUMNS)
                for record in success_records
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


DB_MEMORY_SUMMARY_COLUMNS = [
    "Cluster",
    "db_unique_name",
    "DB_NAME",
    "INSTANCE_NAME",
    "HOST_NAME",
    "snapshot_count",
    "begin_time_min",
    "end_time_max",
    "sga_target_gb_max",
    "sga_max_size_gb_max",
    "sga_used_gb_avg",
    "sga_used_gb_max",
    "sga_used_pct_of_target_avg",
    "sga_used_pct_of_target_max",
    "sga_growth_headroom_gb",
    "sga_buffer_cache_gb_avg",
    "sga_buffer_cache_gb_max",
    "sga_shared_pool_gb_avg",
    "sga_shared_pool_gb_max",
    "sga_large_pool_gb_avg",
    "sga_other_gb_avg",
    "sga_other_gb_max",
    "pga_aggregate_target_gb_max",
    "pga_aggregate_limit_gb_max",
    "pga_allocated_gb_avg",
    "pga_allocated_gb_max",
    "pga_used_gb_avg",
    "pga_used_gb_max",
    "pga_used_pct_of_target_avg",
    "pga_used_pct_of_target_max",
    "pga_max_allocated_gb_max",
    "warnings",
    "info_warnings",
    "warning_warnings",
    "critical_warnings",
    "warning_count",
    "warning_severity",
]

DB_MEMORY_CLUSTER_SUMMARY_COLUMNS = [
    "Cluster",
    "database_count",
    "instance_count",
    "avg_sga_used_gb",
    "max_sga_used_gb",
    "total_latest_sga_used_gb",
    "total_latest_pga_used_gb",
    "total_latest_pga_allocated_gb",
]


def write_db_memory_history_summary_csv(
    records: Iterable[DBMemoryHistoryRecord],
    output_dir: Path,
    *,
    sga_near_max_severity: str = "info",
    sga_near_max_pct: float = 98,
    pga_used_pct_target: float = 80,
    pga_alloc_pct_target: float = 100,
) -> Path:
    """Write per-instance DB memory history rollups to output/db_memory_history_summary.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_memory_history_summary.csv"
    rows = build_db_memory_history_summary_rows(
        records,
        sga_near_max_severity=sga_near_max_severity,
        sga_near_max_pct=sga_near_max_pct,
        pga_used_pct_target=pga_used_pct_target,
        pga_alloc_pct_target=pga_alloc_pct_target,
    )
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_MEMORY_SUMMARY_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def write_db_memory_history_summary_json(
    records: Iterable[DBMemoryHistoryRecord],
    output_dir: Path,
    *,
    sga_near_max_severity: str = "info",
    sga_near_max_pct: float = 98,
    pga_used_pct_target: float = 80,
    pga_alloc_pct_target: float = 100,
) -> Path:
    """Write per-instance DB memory history rollups to output/db_memory_history_summary.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_memory_history_summary.json"
    rows = build_db_memory_history_summary_rows(
        records,
        sga_near_max_severity=sga_near_max_severity,
        sga_near_max_pct=sga_near_max_pct,
        pga_used_pct_target=pga_used_pct_target,
        pga_alloc_pct_target=pga_alloc_pct_target,
    )
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(rows, json_file, indent=2)
        json_file.write("\n")
    return json_path


def write_db_memory_cluster_summary_csv(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write cluster-level DB memory rollups to output/db_memory_cluster_summary.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_memory_cluster_summary.csv"
    rows = build_db_memory_cluster_summary_rows(records)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=DB_MEMORY_CLUSTER_SUMMARY_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def write_db_memory_cluster_summary_json(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write cluster-level DB memory rollups to output/db_memory_cluster_summary.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_memory_cluster_summary.json"
    rows = build_db_memory_cluster_summary_rows(records)
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(rows, json_file, indent=2)
        json_file.write("\n")
    return json_path


def build_db_memory_history_summary_rows(
    records: Iterable[DBMemoryHistoryRecord],
    *,
    sga_near_max_severity: str = "info",
    sga_near_max_pct: float = 98,
    pga_used_pct_target: float = 80,
    pga_alloc_pct_target: float = 100,
) -> list[dict[str, object]]:
    """Build per-instance DB memory summary rows from successful history records."""

    groups: dict[tuple[str, str, str, str, str], list[DBMemoryHistoryRecord]] = {}
    for record in _dedupe_db_history_success(records):
        key = (
            record.Cluster or "",
            record.db_unique_name or "",
            record.DB_NAME or "",
            record.INSTANCE_NAME or "",
            record.HOST_NAME or "",
        )
        groups.setdefault(key, []).append(record)

    rows: list[dict[str, object]] = []
    for key, group_records in sorted(groups.items()):
        cluster, db_unique_name, db_name, instance_name, host_name = key
        sga_pct_values = _ratio_values(group_records, "SGA_USED_GB", "SGA_TARGET_GB")
        pga_pct_values = _ratio_values(
            group_records, "PGA_USED_GB", "PGA_AGGREGATE_TARGET_GB"
        )
        sga_max_size = _max_metric(group_records, "SGA_MAX_SIZE_GB")
        sga_used_max = _max_metric(group_records, "SGA_USED_GB")
        row: dict[str, object] = {
            "Cluster": cluster,
            "db_unique_name": db_unique_name,
            "DB_NAME": db_name,
            "INSTANCE_NAME": instance_name,
            "HOST_NAME": host_name,
            "snapshot_count": len(group_records),
            "begin_time_min": min(
                (r.END_TIME for r in group_records if r.END_TIME), default=""
            ),
            "end_time_max": max(
                (r.END_TIME for r in group_records if r.END_TIME), default=""
            ),
            "sga_target_gb_max": _max_metric(group_records, "SGA_TARGET_GB"),
            "sga_max_size_gb_max": sga_max_size,
            "sga_used_gb_avg": _avg_metric(group_records, "SGA_USED_GB"),
            "sga_used_gb_max": sga_used_max,
            "sga_used_pct_of_target_avg": _avg_values(sga_pct_values),
            "sga_used_pct_of_target_max": _max_values(sga_pct_values),
            "sga_growth_headroom_gb": _metric_difference(sga_max_size, sga_used_max),
            "sga_buffer_cache_gb_avg": _avg_metric(
                group_records, "SGA_BUFFER_CACHE_GB"
            ),
            "sga_buffer_cache_gb_max": _max_metric(
                group_records, "SGA_BUFFER_CACHE_GB"
            ),
            "sga_shared_pool_gb_avg": _avg_metric(group_records, "SGA_SHARED_POOL_GB"),
            "sga_shared_pool_gb_max": _max_metric(group_records, "SGA_SHARED_POOL_GB"),
            "sga_large_pool_gb_avg": _avg_metric(group_records, "SGA_LARGE_POOL_GB"),
            "sga_other_gb_avg": _avg_metric(group_records, "SGA_OTHER_GB"),
            "sga_other_gb_max": _max_metric(group_records, "SGA_OTHER_GB"),
            "pga_aggregate_target_gb_max": _max_metric(
                group_records, "PGA_AGGREGATE_TARGET_GB"
            ),
            "pga_aggregate_limit_gb_max": _max_metric(
                group_records, "PGA_AGGREGATE_LIMIT_GB"
            ),
            "pga_allocated_gb_avg": _avg_metric(group_records, "PGA_ALLOCATED_GB"),
            "pga_allocated_gb_max": _max_metric(group_records, "PGA_ALLOCATED_GB"),
            "pga_used_gb_avg": _avg_metric(group_records, "PGA_USED_GB"),
            "pga_used_gb_max": _max_metric(group_records, "PGA_USED_GB"),
            "pga_used_pct_of_target_avg": _avg_values(pga_pct_values),
            "pga_used_pct_of_target_max": _max_values(pga_pct_values),
            "pga_max_allocated_gb_max": _max_metric(
                group_records, "PGA_MAX_ALLOCATED_GB"
            ),
        }
        row.update(
            _db_memory_warning_summary(
                row,
                sga_near_max_severity=sga_near_max_severity,
                sga_near_max_pct=sga_near_max_pct,
                pga_used_pct_target=pga_used_pct_target,
                pga_alloc_pct_target=pga_alloc_pct_target,
            )
        )
        rows.append(row)
    return rows


def build_db_memory_cluster_summary_rows(
    records: Iterable[DBMemoryHistoryRecord],
) -> list[dict[str, object]]:
    """Build cluster-level DB memory summary rows from successful history records."""

    clusters: dict[str, list[DBMemoryHistoryRecord]] = {}
    for record in _dedupe_db_history_success(records):
        clusters.setdefault(record.Cluster or "", []).append(record)

    rows: list[dict[str, object]] = []
    for cluster, cluster_records in sorted(clusters.items()):
        databases = {
            r.db_unique_name or r.DB_NAME
            for r in cluster_records
            if r.db_unique_name or r.DB_NAME
        }
        instances = {
            (r.db_unique_name or r.DB_NAME, r.INSTANCE_NAME, r.HOST_NAME)
            for r in cluster_records
            if r.INSTANCE_NAME or r.HOST_NAME
        }
        latest_by_instance: dict[tuple[str, str, str], DBMemoryHistoryRecord] = {}
        for record in cluster_records:
            key = (
                record.db_unique_name or record.DB_NAME,
                record.INSTANCE_NAME,
                record.HOST_NAME,
            )
            current = latest_by_instance.get(key)
            if current is None or (record.END_TIME or "") >= (current.END_TIME or ""):
                latest_by_instance[key] = record
        latest_records = list(latest_by_instance.values())
        rows.append(
            {
                "Cluster": cluster,
                "database_count": len(databases),
                "instance_count": len(instances),
                "avg_sga_used_gb": _avg_metric(cluster_records, "SGA_USED_GB"),
                "max_sga_used_gb": _max_metric(cluster_records, "SGA_USED_GB"),
                "total_latest_sga_used_gb": _sum_metric(latest_records, "SGA_USED_GB"),
                "total_latest_pga_used_gb": _sum_metric(latest_records, "PGA_USED_GB"),
                "total_latest_pga_allocated_gb": _sum_metric(
                    latest_records, "PGA_ALLOCATED_GB"
                ),
            }
        )
    return rows


def _safe_float(value: Any) -> float | None:
    """Convert numeric collector values, including strings like '.03', to float."""

    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_values(records: Iterable[DBMemoryHistoryRecord], field: str) -> list[float]:
    return [
        value
        for value in (_safe_float(getattr(record, field, None)) for record in records)
        if value is not None
    ]


def _avg_metric(records: Iterable[DBMemoryHistoryRecord], field: str) -> float | str:
    return _avg_values(_metric_values(records, field))


def _max_metric(records: Iterable[DBMemoryHistoryRecord], field: str) -> float | str:
    return _max_values(_metric_values(records, field))


def _sum_metric(records: Iterable[DBMemoryHistoryRecord], field: str) -> float:
    return _round_metric(sum(_metric_values(records, field)))


def _ratio_values(
    records: Iterable[DBMemoryHistoryRecord], numerator: str, denominator: str
) -> list[float]:
    values: list[float] = []
    for record in records:
        num = _safe_float(getattr(record, numerator, None))
        den = _safe_float(getattr(record, denominator, None))
        if num is None or den is None or den <= 0:
            continue
        values.append((num / den) * 100)
    return values


def _avg_values(values: list[float]) -> float | str:
    if not values:
        return ""
    return _round_metric(sum(values) / len(values))


def _max_values(values: list[float]) -> float | str:
    if not values:
        return ""
    return _round_metric(max(values))


def _round_metric(value: float) -> float:
    rounded = round(value, 4)
    if rounded == -0.0:
        return 0.0
    return rounded


def _metric_difference(minuend: float | str, subtrahend: float | str) -> float | str:
    left = _safe_float(minuend)
    right = _safe_float(subtrahend)
    if left is None or right is None:
        return ""
    return _round_metric(left - right)


def _db_memory_warning_summary(
    row: dict[str, object],
    *,
    sga_near_max_severity: str,
    sga_near_max_pct: float,
    pga_used_pct_target: float,
    pga_alloc_pct_target: float,
) -> dict[str, object]:
    """Classify each memory finding into exactly one severity category."""

    informational: set[str] = set()
    warning: set[str] = set()
    critical: set[str] = set()

    sga_target = _safe_float(row.get("sga_target_gb_max"))
    sga_max = _safe_float(row.get("sga_max_size_gb_max"))
    sga_used_avg = _safe_float(row.get("sga_used_gb_avg"))
    sga_used_max = _safe_float(row.get("sga_used_gb_max"))
    pga_target = _safe_float(row.get("pga_aggregate_target_gb_max"))
    pga_limit = _safe_float(row.get("pga_aggregate_limit_gb_max"))
    pga_allocated = _safe_float(row.get("pga_allocated_gb_max"))
    pga_used_pct = _safe_float(row.get("pga_used_pct_of_target_max"))
    sga_growth_headroom = _safe_float(row.get("sga_growth_headroom_gb"))

    if sga_target == 0 and (
        (sga_max is not None and sga_max > 0)
        or (sga_used_avg is not None and sga_used_avg > 0)
    ):
        informational.add("SGA_TARGET_ZERO")
    if sga_target == 0 and sga_used_avg is not None and sga_used_avg > 0:
        informational.add("AMM_OR_MANUAL_SGA")
    if sga_max is not None and sga_max > 0 and sga_used_max is not None:
        sga_used_pct_of_max = sga_used_max / sga_max * 100
        if sga_used_pct_of_max >= 90:
            informational.add("SGA_USED_OVER_90_PCT")
        if sga_used_pct_of_max >= sga_near_max_pct:
            configured_near_max_severity = sga_near_max_severity.strip().lower()
            if configured_near_max_severity not in {"info", "warning"}:
                raise ValueError(
                    "sga_near_max_severity must be either 'info' or 'warning'."
                )
            target_equals_max = sga_target is not None and sga_target == sga_max
            target_below_max = sga_target is not None and sga_target < sga_max
            limited_growth_headroom = (
                sga_growth_headroom is not None and sga_growth_headroom <= 1
            )
            if target_equals_max:
                informational.add("SGA_NEAR_MAX")
            elif target_below_max and limited_growth_headroom:
                warning.add("SGA_NEAR_MAX")
            else:
                informational.add("SGA_NEAR_MAX")
        if sga_used_max > sga_max:
            critical.add("SGA_USED_OVER_MAX_SIZE")

    if pga_used_pct is not None and pga_used_pct >= pga_used_pct_target:
        warning.add("PGA_USED_OVER_TARGET")
    if (
        pga_target is not None
        and pga_target > 0
        and pga_allocated is not None
        and pga_allocated > pga_target
        and pga_allocated / pga_target * 100 > pga_alloc_pct_target
    ):
        critical.add("PGA_ALLOC_OVER_TARGET")
    if pga_limit == 0:
        informational.add("PGA_LIMIT_ZERO")

    all_warnings = informational | warning | critical
    if critical:
        severity = "CRITICAL"
    elif warning:
        severity = "WARNING"
    elif informational:
        severity = "INFO"
    else:
        severity = "OK"

    return {
        "warnings": ";".join(sorted(all_warnings)),
        "info_warnings": ";".join(sorted(informational)),
        "warning_warnings": ";".join(sorted(warning)),
        "critical_warnings": ";".join(sorted(critical)),
        "warning_count": len(all_warnings),
        "warning_severity": severity,
    }


def write_db_memory_history_errors_csv(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write failed DB SGA/PGA AWR collection rows to output/db_memory_history_errors.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "db_memory_history_errors.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=DB_MEMORY_ERROR_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for record in _db_history_error_records(records):
            writer.writerow(_db_history_error_row(record, DB_MEMORY_ERROR_COLUMNS))
    return csv_path


def write_db_memory_history_errors_json(
    records: Iterable[DBMemoryHistoryRecord], output_dir: Path
) -> Path:
    """Write failed DB SGA/PGA AWR collection rows to output/db_memory_history_errors.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db_memory_history_errors.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(
            [
                _db_history_error_row(record, DB_MEMORY_ERROR_COLUMNS)
                for record in _db_history_error_records(records)
            ],
            json_file,
            indent=2,
        )
        json_file.write("\n")
    return json_path


def _db_history_key(
    record: DBPerformanceRecord | DBMemoryHistoryRecord,
) -> tuple[str, ...]:
    if isinstance(record, DBMemoryHistoryRecord):
        return (
            record.Cluster,
            record.db_unique_name,
            record.INSTANCE_NAME,
            record.END_TIME,
        )
    return (
        record.Cluster,
        record.db_unique_name,
        record.DB_NAME,
        record.INSTANCE_NAME,
        record.END_TIME,
    )


def _dedupe_db_history_success(
    records: Iterable[DBPerformanceRecord] | Iterable[DBMemoryHistoryRecord],
) -> list[DBPerformanceRecord] | list[DBMemoryHistoryRecord]:
    deduped: dict[tuple[str, ...], DBPerformanceRecord | DBMemoryHistoryRecord] = {}
    for record in records:
        if record.collection_status != "success":
            continue
        key = _db_history_key(record)
        if key in deduped:
            if not isinstance(record, DBMemoryHistoryRecord):
                deduped[key].duplicate_count = (
                    int(getattr(deduped[key], "duplicate_count", 1) or 1) + 1
                )
            continue
        record.duplicate_count = 1
        deduped[key] = record
    return list(deduped.values())


def _db_history_error_records(
    records: Iterable[DBPerformanceRecord] | Iterable[DBMemoryHistoryRecord],
) -> list[DBPerformanceRecord] | list[DBMemoryHistoryRecord]:
    return [record for record in records if record.collection_status != "success"]


def _db_history_success_row(
    record: DBPerformanceRecord | DBMemoryHistoryRecord, columns: list[str]
) -> dict[str, object]:
    return {column: getattr(record, column, "") for column in columns}


def _db_history_error_row(
    record: DBPerformanceRecord | DBMemoryHistoryRecord, columns: list[str]
) -> dict[str, object]:
    return {column: getattr(record, column, "") for column in columns}


def write_health_summary_csv(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    output_dir: Path,
    version_records: Iterable[VersionInventoryRecord] | None = None,
    db_performance_records: Iterable[DBPerformanceRecord] | None = None,
    db_memory_records: Iterable[DBMemoryHistoryRecord] | None = None,
) -> Path:
    """Write the combined dashboard-ready health feed to output/health_summary.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "health_summary.csv"
    rows = build_health_summary_rows(
        os_records,
        asm_records,
        hugepages_records,
        db_records,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=HEALTH_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def write_health_summary_html(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    output_dir: Path,
    version_records: Iterable[VersionInventoryRecord] | None = None,
    db_performance_records: Iterable[DBPerformanceRecord] | None = None,
    db_memory_records: Iterable[DBMemoryHistoryRecord] | None = None,
) -> Path:
    """Write a simple color-coded health summary table to output/health_summary.html."""

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "health_summary.html"
    rows = build_health_summary_rows(
        os_records,
        asm_records,
        hugepages_records,
        db_records,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    html_path.write_text(_health_summary_html(rows), encoding="utf-8")
    return html_path


def write_health_summary_json(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    output_dir: Path,
    version_records: Iterable[VersionInventoryRecord] | None = None,
    db_performance_records: Iterable[DBPerformanceRecord] | None = None,
    db_memory_records: Iterable[DBMemoryHistoryRecord] | None = None,
) -> Path:
    """Write the combined dashboard-ready health feed to output/health_summary.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "health_summary.json"
    rows = build_health_summary_rows(
        os_records,
        asm_records,
        hugepages_records,
        db_records,
        version_records,
        db_performance_records,
        db_memory_records,
    )
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(rows, json_file, indent=2)
        json_file.write("\n")
    return json_path


def build_health_summary_rows(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    version_records: Iterable[VersionInventoryRecord] | None = None,
    db_performance_records: Iterable[DBPerformanceRecord] | None = None,
    db_memory_records: Iterable[DBMemoryHistoryRecord] | None = None,
) -> list[dict[str, object]]:
    """Merge collector health signals into a single normalized row set."""

    rows: list[dict[str, object]] = []
    rows.extend(_filesystem_health_rows(os_records))
    rows.extend(_asm_health_rows(asm_records))
    rows.extend(_hugepages_health_rows(hugepages_records))
    rows.extend(_db_inventory_health_rows(db_records))
    rows.extend(_version_inventory_health_rows(version_records or []))
    rows.extend(_db_performance_health_rows(db_performance_records or []))
    rows.extend(_db_memory_health_rows(db_memory_records or []))
    return rows


def health_summary_counts(rows: Iterable[dict[str, object]]) -> dict[str, int]:
    """Count normalized health rows by dashboard warning level."""

    counts = {"CRITICAL": 0, "WARNING": 0, "OK": 0}
    for row in rows:
        level = _normalize_health_level(row.get("warning_level"))
        if level in counts:
            counts[level] += 1
    return counts


def _filesystem_health_rows(
    records: Iterable[OSCollectionRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if record.status != "ok":
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "FILESYSTEM",
                    "host",
                    "collection_status",
                    record.status,
                    "CRITICAL",
                    record.error,
                    record.collected_at,
                )
            )
            continue
        for filesystem in record.filesystems:
            use_pct = _percent_value(filesystem.get("use_percent"))
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "FILESYSTEM",
                    str(
                        filesystem.get("mounted_on")
                        or filesystem.get("filesystem")
                        or "filesystem"
                    ),
                    "use_pct",
                    use_pct,
                    _filesystem_warning_level(use_pct),
                    _details(
                        filesystem=filesystem.get("filesystem"),
                        type=filesystem.get("type"),
                        size=filesystem.get("size"),
                        used=filesystem.get("used"),
                        available=filesystem.get("available"),
                    ),
                    record.collected_at,
                )
            )
    return rows


def _asm_health_rows(records: Iterable[ASMDiskgroupRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if record.asm_collection_status != "success" or not record.diskgroup_name:
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "ASM",
                    record.diskgroup_name or "ASM",
                    "collection_status",
                    record.asm_collection_status or "failed",
                    _normalize_health_level(record.warning_level),
                    record.asm_error or record.asm_collection_error,
                    record.collected_at,
                )
            )
            continue
        rows.append(
            _health_row(
                record.cluster,
                record.host,
                "ASM",
                record.diskgroup_name,
                "used_pct",
                record.used_pct,
                _normalize_health_level(record.warning_level),
                _details(
                    state=record.state,
                    type=record.type,
                    total_tb=record.total_tb,
                    free_tb=record.free_tb,
                    usable_tb=record.usable_tb,
                    free_pct=record.free_pct,
                    usable_pct=record.usable_pct,
                ),
                record.collected_at,
            )
        )
    return rows


def _hugepages_health_rows(
    records: Iterable[HugePagesRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        metric = (
            "free_pct" if record.collection_status == "success" else "collection_status"
        )
        value: object = (
            record.hugepages_free_pct
            if record.collection_status == "success"
            else record.collection_status
        )
        rows.append(
            _health_row(
                record.cluster,
                record.host,
                "HUGEPAGES",
                "host",
                metric,
                value,
                _normalize_health_level(record.warning_level),
                _details(
                    total=record.hugepages_total,
                    free=record.hugepages_free,
                    used=record.hugepages_used,
                    used_pct=record.hugepages_used_pct,
                    collection_status=record.collection_status,
                    collection_error=record.collection_error,
                ),
                record.collected_at,
            )
        )
    return rows


def _version_inventory_health_rows(
    records: Iterable[VersionInventoryRecord],
) -> list[dict[str, object]]:
    records = list(records)
    rows: list[dict[str, object]] = []
    for record in records:
        if record.collection_status != "success":
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "VERSION_INVENTORY",
                    "host",
                    "collection_status",
                    record.collection_status,
                    "CRITICAL",
                    record.collection_error,
                    record.collected_at,
                )
            )
            continue
        if not record.imageinfo_path:
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "VERSION_INVENTORY",
                    "imageinfo",
                    "imageinfo_available",
                    "unavailable",
                    "WARNING",
                    "imageinfo command was not found on this host",
                    record.collected_at,
                )
            )
        elif record.image_status.strip().lower() != "success":
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "VERSION_INVENTORY",
                    "image_status",
                    "image_status",
                    record.image_status or "unknown",
                    "WARNING",
                    _details(
                        image_version=record.image_version,
                        exadata_software_version=record.exadata_software_version,
                    ),
                    record.collected_at,
                )
            )

    rows.extend(_cluster_version_drift_rows(records, "image_version", "image_version"))
    rows.extend(
        _cluster_version_drift_rows(
            records, "gi_release_patch_string", "gi_release_patch_string"
        )
    )
    return rows


def _cluster_version_drift_rows(
    records: list[VersionInventoryRecord], attribute: str, metric: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_cluster: dict[str, list[VersionInventoryRecord]] = {}
    for record in records:
        if record.collection_status == "success":
            by_cluster.setdefault(record.cluster, []).append(record)

    for cluster, cluster_records in by_cluster.items():
        values_by_host = {
            record.host: str(getattr(record, attribute) or "")
            for record in cluster_records
        }
        distinct_values = {value for value in values_by_host.values() if value}
        if len(distinct_values) <= 1:
            continue
        collected_at = max(
            (record.collected_at for record in cluster_records), default=""
        )
        rows.append(
            _health_row(
                cluster,
                "cluster",
                "VERSION_INVENTORY",
                cluster,
                metric,
                "mismatch",
                "CRITICAL",
                {"values_by_host": values_by_host},
                collected_at,
            )
        )
    return rows


def _db_inventory_health_rows(
    records: Iterable[DBInventoryRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if record.status != "ok":
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "DB_INVENTORY",
                    "host",
                    "status",
                    record.status,
                    "CRITICAL",
                    record.error,
                    record.collected_at,
                )
            )
        elif not record.databases:
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "DB_INVENTORY",
                    "host",
                    "status",
                    record.status,
                    "OK",
                    _details(databases=0, pmon_processes=len(record.pmon_processes)),
                    record.collected_at,
                )
            )
        else:
            for database in record.databases:
                status_text = record.srvctl_status.get(database, "discovered")
                rows.append(
                    _health_row(
                        record.cluster,
                        record.host,
                        "DB_INVENTORY",
                        database,
                        "status",
                        _compact_status(status_text),
                        _db_warning_level(status_text),
                        _details(
                            status=status_text,
                            config=record.srvctl_config.get(database, ""),
                        ),
                        record.collected_at,
                    )
                )

        for detail in record.db_resource_details:
            status = str(detail.get("collection_status") or "").lower()
            object_name = str(
                detail.get("db_unique_name") or detail.get("DB_NAME") or "database"
            )
            collected_at = str(
                detail.get("collected_at")
                or detail.get("Collected_At")
                or record.collected_at
            )
            if status == "success":
                db_used_pct = _db_resource_used_pct(detail)
                rows.append(
                    _health_row(
                        record.cluster,
                        record.host,
                        "DB_RESOURCE",
                        object_name,
                        "db_used_pct",
                        db_used_pct,
                        _db_resource_pct_warning_level(db_used_pct),
                        _details(
                            db_name=detail.get("DB_NAME") or detail.get("db_name"),
                            db_size_gb=detail.get("DB_SIZE_GB")
                            or detail.get("db_size_gb"),
                            used_db_size_gb=detail.get("USED_DB_SIZE_GB")
                            or detail.get("used_db_size_gb"),
                            oracle_home=detail.get("oracle_home"),
                            oracle_sid=detail.get("oracle_sid"),
                            size_source=detail.get("size_source"),
                        ),
                        collected_at,
                    )
                )
            elif status == "failed":
                rows.append(
                    _health_row(
                        record.cluster,
                        record.host,
                        "DB_RESOURCE",
                        object_name,
                        "collection_status",
                        "failed",
                        "WARNING",
                        _details(
                            collection_error=detail.get("collection_error"),
                            error_category=detail.get("error_category"),
                            sql_returncode=detail.get("sql_returncode"),
                            sql_stderr=detail.get("sql_stderr"),
                        ),
                        collected_at,
                    )
                )
    return rows


def _db_performance_health_rows(
    records: Iterable[DBPerformanceRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if record.collection_status == "failed":
            rows.append(
                _health_row(
                    record.Cluster,
                    record.source_host or record.HOST_NAME,
                    "DB_PERFORMANCE",
                    record.db_unique_name or record.DB_NAME or "DB_PERFORMANCE",
                    "collection_status",
                    "failed",
                    "WARNING",
                    _details(
                        collection_error=record.collection_error,
                        error_category=record.error_category,
                    ),
                    record.Collected_At,
                )
            )
            continue
        if record.collection_status == "skipped":
            continue
        avg = _numeric_value(record.HOST_CPU_UTIL_PCT_AVG)
        level = "CRITICAL" if avg >= 95 else "WARNING" if avg >= 85 else "OK"
        rows.append(
            _health_row(
                record.Cluster,
                record.HOST_NAME or record.source_host,
                "DB_PERFORMANCE",
                record.DB_NAME or record.db_unique_name or record.INSTANCE_NAME,
                "host_cpu_util_pct_avg",
                avg,
                level,
                _details(
                    instance_name=record.INSTANCE_NAME,
                    end_time=record.END_TIME,
                    total_iops_avg=record.TOTAL_IOPS_AVG,
                ),
                record.Collected_At,
            )
        )
    return rows


def _db_memory_health_rows(
    records: Iterable[DBMemoryHistoryRecord],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        if record.collection_status == "failed":
            rows.append(
                _health_row(
                    record.Cluster,
                    record.source_host or record.HOST_NAME,
                    "DB_MEMORY",
                    record.db_unique_name or record.DB_NAME or "DB_MEMORY",
                    "collection_status",
                    "failed",
                    "WARNING",
                    _details(
                        collection_error=record.collection_error,
                        error_category=record.error_category,
                    ),
                    record.Collected_At,
                )
            )
            continue
        if record.collection_status == "skipped":
            continue
        sga_used = _numeric_value(record.SGA_USED_GB)
        sga_target = _numeric_value(record.SGA_TARGET_GB)
        if sga_target > 0:
            pct = round((sga_used / sga_target) * 100, 2)
            level = "CRITICAL" if pct >= 98 else "WARNING" if pct >= 90 else "OK"
            rows.append(
                _health_row(
                    record.Cluster,
                    record.HOST_NAME or record.source_host,
                    "DB_MEMORY",
                    record.DB_NAME or record.db_unique_name or record.INSTANCE_NAME,
                    "sga_used_pct_of_target",
                    pct,
                    level,
                    _details(
                        instance_name=record.INSTANCE_NAME,
                        end_time=record.END_TIME,
                        sga_used_gb=record.SGA_USED_GB,
                        sga_target_gb=record.SGA_TARGET_GB,
                    ),
                    record.Collected_At,
                )
            )
        pga_alloc = _numeric_value(record.PGA_ALLOCATED_GB)
        pga_limit = _numeric_value(record.PGA_AGGREGATE_LIMIT_GB)
        if pga_limit > 0:
            pct = round((pga_alloc / pga_limit) * 100, 2)
            level = "CRITICAL" if pct >= 98 else "WARNING" if pct >= 90 else "OK"
            rows.append(
                _health_row(
                    record.Cluster,
                    record.HOST_NAME or record.source_host,
                    "DB_MEMORY",
                    record.DB_NAME or record.db_unique_name or record.INSTANCE_NAME,
                    "pga_allocated_pct_of_limit",
                    pct,
                    level,
                    _details(
                        instance_name=record.INSTANCE_NAME,
                        end_time=record.END_TIME,
                        pga_allocated_gb=record.PGA_ALLOCATED_GB,
                        pga_limit_gb=record.PGA_AGGREGATE_LIMIT_GB,
                    ),
                    record.Collected_At,
                )
            )
    return rows


def _health_row(
    cluster: str,
    host: str,
    category: str,
    object_name: str,
    metric: str,
    value: object,
    warning_level: str,
    details: object,
    collected_at: str,
) -> dict[str, object]:
    return {
        "cluster": cluster,
        "host": host,
        "category": category,
        "object_name": object_name,
        "metric": metric,
        "value": value,
        "warning_level": _normalize_health_level(warning_level),
        "recommendation": _health_recommendation(
            category, warning_level, metric, value
        ),
        "details": (
            details if isinstance(details, str) else json.dumps(details, sort_keys=True)
        ),
        "collected_at": collected_at,
    }


def _filesystem_warning_level(use_pct: float) -> str:
    if use_pct >= 95:
        return "CRITICAL"
    if use_pct >= 85:
        return "WARNING"
    return "OK"


def _db_resource_pct_warning_level(value: object) -> str:
    pct = _numeric_value(value)
    if pct >= 95:
        return "CRITICAL"
    if pct >= 85:
        return "WARNING"
    return "OK"


def _db_resource_used_pct(detail: dict[str, object]) -> object:
    size = _optional_float(detail.get("DB_SIZE_GB") or detail.get("db_size_gb"))
    used = _optional_float(
        detail.get("USED_DB_SIZE_GB") or detail.get("used_db_size_gb")
    )
    if size in (None, 0) or used is None:
        return ""
    return round((used / size) * 100, 2)


def _health_recommendation(
    category: str, warning_level: str, metric: str, value: object
) -> str:
    level = _normalize_health_level(warning_level)
    if level not in {"CRITICAL", "WARNING"}:
        return ""

    if category == "FILESYSTEM" and metric == "use_pct":
        use_pct = _numeric_value(value)
        if level == "CRITICAL" and use_pct >= 95:
            return "Immediate cleanup or expansion required."
        if level == "WARNING" and use_pct >= 85:
            return "Review growth and cleanup candidates."

    if category == "HUGEPAGES" and metric == "free_pct":
        free_pct = _numeric_value(value)
        if level == "CRITICAL" and free_pct <= 5:
            return "Review DB SGA/HugePages allocation; risk of HugePages exhaustion."
        if level == "WARNING" and free_pct <= 10:
            return "Monitor HugePages free count."

    if category == "DB_RESOURCE" and metric == "db_used_pct":
        used_pct = _numeric_value(value)
        if level == "CRITICAL" and used_pct >= 95:
            return "Review database space usage and growth immediately."
        if level == "WARNING" and used_pct >= 85:
            return "Review database growth trend and reclaim opportunities."

    if (
        category == "DB_RESOURCE"
        and metric == "collection_status"
        and str(value) == "failed"
    ):
        return "Review SYSDBA connectivity, database state, and SQL error details."

    if category == "DB_PERFORMANCE":
        if metric == "host_cpu_util_pct_avg":
            return "Review DB workload and host CPU pressure for the affected AWR interval."
        if metric == "collection_status":
            return "Verify Diagnostics Pack/AWR licensing, DBA_HIST view access, and SYSDBA connectivity."

    if category == "DB_MEMORY":
        if metric in {"sga_used_pct_of_target", "pga_allocated_pct_of_limit"}:
            return "Review SGA/PGA sizing and recent memory pressure for the affected AWR interval."
        if metric == "collection_status":
            return "Verify Diagnostics Pack/AWR licensing, DBA_HIST memory view access, and SYSDBA connectivity."

    if category == "VERSION_INVENTORY":
        if metric == "imageinfo_available":
            return "Install or expose imageinfo on the host, or verify Exadata tooling is available."
        if metric == "image_status":
            return "Review imageinfo output; image status is not success."
        if metric == "image_version":
            return "Align Exadata image versions across nodes in the cluster."
        if metric == "gi_release_patch_string":
            return "Align GI release patch string across nodes in the cluster."

    return ""


def _health_summary_html(rows: list[dict[str, object]]) -> str:
    columns = [
        "cluster",
        "host",
        "category",
        "object_name",
        "metric",
        "value",
        "warning_level",
        "recommendation",
    ]
    table_rows = []
    for row in rows:
        level = _normalize_health_level(row.get("warning_level"))
        cells = "".join(
            f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns
        )
        table_rows.append(f'<tr class="{level.lower()}">{cells}</tr>')
    if not table_rows:
        table_rows.append(
            f'<tr class="ok"><td colspan="{len(columns)}">No health records collected.</td></tr>'
        )

    header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body = "\n".join(table_rows)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Exadata Health Summary</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
    th {{ background: #f2f2f2; }}
    tr.critical {{ background: #f8d7da; color: #842029; }}
    tr.warning {{ background: #fff3cd; color: #664d03; }}
    tr.ok {{ background: #d1e7dd; color: #0f5132; }}
  </style>
</head>
<body>
  <h1>Exadata Health Summary</h1>
  <table>
    <thead><tr>{header}</tr></thead>
    <tbody>
{body}
    </tbody>
  </table>
</body>
</html>
"""


def _numeric_value(value: object) -> float:
    try:
        return float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return 0.0


def _db_warning_level(status_text: str) -> str:
    lowered = status_text.lower()
    if any(
        token in lowered
        for token in ("failed", "failure", "error", "not running", "offline", "unknown")
    ):
        return "WARNING"
    return "OK"


def _normalize_health_level(level: object) -> str:
    normalized = str(level or "OK").strip().upper()
    if normalized in {"CRITICAL", "WARNING", "OK"}:
        return normalized
    if normalized in {"ERROR", "FAILED", "FAIL"}:
        return "CRITICAL"
    if normalized in {"INFO", "SKIPPED", ""}:
        return "OK"
    return "WARNING"


def _percent_value(value: object) -> float:
    text = str(value or "0").strip().rstrip("%")
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def _details(**items: object) -> str:
    clean = {key: value for key, value in items.items() if value not in (None, "")}
    return json.dumps(clean, sort_keys=True)


def _compact_status(status_text: str) -> str:
    lines = [line.strip() for line in status_text.splitlines() if line.strip()]
    if not lines:
        return "discovered"
    return " | ".join(lines)



def _asm_summary_rows(records: Iterable[ASMDiskgroupRecord]) -> list[dict[str, object]]:
    by_diskgroup: dict[tuple[str, str], ASMDiskgroupRecord] = {}
    for record in records:
        if (
            record.record_type == "host_metadata"
            or record.asm_collection_status != "success"
            or not record.diskgroup_name
        ):
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
