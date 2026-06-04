"""CSV and JSON report writers."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Iterable

from collectors.db_inventory_collector import DBInventoryRecord
from collectors.os_collector import OSCollectionRecord
from collectors.asm_diskgroups_collector import ASMDiskgroupRecord
from collectors.hugepages_collector import HugePagesRecord
from collectors.version_inventory_collector import VersionInventoryRecord

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

VERSION_INVENTORY_FIELDS = [
    "cluster", "host", "address", "collected_at", "collection_status", "collection_error",
    "ssh_returncode", "image_version", "exadata_software_version", "image_activated",
    "image_status", "gi_active_version", "gi_software_patch_level", "gi_release_version",
    "gi_release_patch_level", "gi_release_patch_string", "gi_release_patch_list",
    "imageinfo_json",
]

HEALTH_SUMMARY_FIELDS = [
    "cluster", "host", "category", "object_name", "metric", "value", "warning_level",
    "recommendation", "details", "collected_at",
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


def write_version_inventory_csv(records: Iterable[VersionInventoryRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "version_inventory.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=VERSION_INVENTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())
    return csv_path


def write_version_inventory_json(records: Iterable[VersionInventoryRecord], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "version_inventory.json"
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump([record.to_json_dict() for record in records], json_file, indent=2)
        json_file.write("\n")
    return json_path


def write_health_summary_csv(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    output_dir: Path,
    version_records: Iterable[VersionInventoryRecord] | None = None,
) -> Path:
    """Write the combined dashboard-ready health feed to output/health_summary.csv."""

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "health_summary.csv"
    rows = build_health_summary_rows(os_records, asm_records, hugepages_records, db_records, version_records)
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
) -> Path:
    """Write a simple color-coded health summary table to output/health_summary.html."""

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "health_summary.html"
    rows = build_health_summary_rows(os_records, asm_records, hugepages_records, db_records, version_records)
    html_path.write_text(_health_summary_html(rows), encoding="utf-8")
    return html_path


def write_health_summary_json(
    os_records: Iterable[OSCollectionRecord],
    asm_records: Iterable[ASMDiskgroupRecord],
    hugepages_records: Iterable[HugePagesRecord],
    db_records: Iterable[DBInventoryRecord],
    output_dir: Path,
    version_records: Iterable[VersionInventoryRecord] | None = None,
) -> Path:
    """Write the combined dashboard-ready health feed to output/health_summary.json."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "health_summary.json"
    rows = build_health_summary_rows(os_records, asm_records, hugepages_records, db_records, version_records)
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
) -> list[dict[str, object]]:
    """Merge collector health signals into a single normalized row set."""

    rows: list[dict[str, object]] = []
    rows.extend(_filesystem_health_rows(os_records))
    rows.extend(_asm_health_rows(asm_records))
    rows.extend(_hugepages_health_rows(hugepages_records))
    rows.extend(_db_inventory_health_rows(db_records))
    rows.extend(_version_inventory_health_rows(version_records or []))
    return rows


def health_summary_counts(rows: Iterable[dict[str, object]]) -> dict[str, int]:
    """Count normalized health rows by dashboard warning level."""

    counts = {"CRITICAL": 0, "WARNING": 0, "OK": 0}
    for row in rows:
        level = _normalize_health_level(row.get("warning_level"))
        if level in counts:
            counts[level] += 1
    return counts


def _filesystem_health_rows(records: Iterable[OSCollectionRecord]) -> list[dict[str, object]]:
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
                    str(filesystem.get("mounted_on") or filesystem.get("filesystem") or "filesystem"),
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
    for record in _diskgroup_records(records):
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


def _hugepages_health_rows(records: Iterable[HugePagesRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        metric = "free_pct" if record.collection_status == "success" else "collection_status"
        value: object = record.hugepages_free_pct if record.collection_status == "success" else record.collection_status
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


def _version_inventory_health_rows(records: Iterable[VersionInventoryRecord]) -> list[dict[str, object]]:
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
        if record.image_status.strip().lower() != "success":
            rows.append(
                _health_row(
                    record.cluster,
                    record.host,
                    "VERSION_INVENTORY",
                    "image_status",
                    "image_status",
                    record.image_status or "unknown",
                    "WARNING",
                    _details(image_version=record.image_version, exadata_software_version=record.exadata_software_version),
                    record.collected_at,
                )
            )

    rows.extend(_cluster_version_drift_rows(records, "image_version", "image_version"))
    rows.extend(_cluster_version_drift_rows(records, "gi_release_patch_string", "gi_release_patch_string"))
    return rows


def _cluster_version_drift_rows(records: list[VersionInventoryRecord], attribute: str, metric: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_cluster: dict[str, list[VersionInventoryRecord]] = {}
    for record in records:
        if record.collection_status == "success":
            by_cluster.setdefault(record.cluster, []).append(record)

    for cluster, cluster_records in by_cluster.items():
        values_by_host = {record.host: str(getattr(record, attribute) or "") for record in cluster_records}
        distinct_values = {value for value in values_by_host.values() if value}
        if len(distinct_values) <= 1:
            continue
        collected_at = max((record.collected_at for record in cluster_records), default="")
        rows.append(
            _health_row(
                cluster,
                "cluster",
                "VERSION_INVENTORY",
                cluster,
                metric,
                "mismatch",
                "WARNING",
                {"values_by_host": values_by_host},
                collected_at,
            )
        )
    return rows


def _db_inventory_health_rows(records: Iterable[DBInventoryRecord]) -> list[dict[str, object]]:
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
            continue
        if not record.databases:
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
            continue
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
                    _details(status=status_text, config=record.srvctl_config.get(database, "")),
                    record.collected_at,
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
        "recommendation": _health_recommendation(category, warning_level, metric, value),
        "details": details if isinstance(details, str) else json.dumps(details, sort_keys=True),
        "collected_at": collected_at,
    }


def _filesystem_warning_level(use_pct: float) -> str:
    if use_pct >= 95:
        return "CRITICAL"
    if use_pct >= 85:
        return "WARNING"
    return "OK"



def _health_recommendation(category: str, warning_level: str, metric: str, value: object) -> str:
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

    if category == "VERSION_INVENTORY":
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
        cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns)
        table_rows.append(f'<tr class="{level.lower()}">{cells}</tr>')
    if not table_rows:
        table_rows.append(f'<tr class="ok"><td colspan="{len(columns)}">No health records collected.</td></tr>')

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
    if any(token in lowered for token in ("failed", "failure", "error", "not running", "offline", "unknown")):
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
