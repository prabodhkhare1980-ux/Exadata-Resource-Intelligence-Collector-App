"""Normalizers adapted from the Streamlit ``app.py`` for the Dash dashboard.

These helpers shape collector output dataframes into stable, predictable
columns for KPIs, charts, and tables. They never read from disk or call
collectors; they only operate on dataframes already loaded by the data loader.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

HEALTH_LEVELS = ["CRITICAL", "WARNING", "INFO", "OK"]
LEVEL_ORDER = {level: index for index, level in enumerate(HEALTH_LEVELS)}
LEVEL_COLORS = {
    "CRITICAL": "#d92d20",
    "WARNING": "#f59e0b",
    "INFO": "#2563eb",
    "OK": "#16a34a",
}


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return ``df`` with every requested column present (NA if missing)."""

    output = df.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output


def normalize_severity(value: Any) -> str:
    """Normalize a severity value to one of CRITICAL/WARNING/INFO/OK."""

    if pd.isna(value):
        return "OK"
    level = str(value).upper().strip()
    return level if level in HEALTH_LEVELS else "OK"


def severity_from_pct(
    value: Any, warning: float = 80.0, critical: float = 90.0
) -> str:
    """Derive CRITICAL/WARNING/OK from a used-percent value."""

    pct = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(pct):
        return "OK"
    if float(pct) >= critical:
        return "CRITICAL"
    if float(pct) >= warning:
        return "WARNING"
    return "OK"


def parse_json_value(value: Any) -> Any:
    """Parse a nested JSON string when CSV output stores JSON text."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def normalize_asm(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare ASM rows for summaries, charts, and filters."""

    columns = [
        "cluster",
        "host",
        "diskgroup_name",
        "total_tb",
        "free_tb",
        "usable_tb",
        "used_pct",
        "warning_level",
    ]
    table = ensure_columns(df, columns)[columns].copy()
    for column in ["total_tb", "free_tb", "usable_tb", "used_pct"]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    # Derive used_pct if missing but free/total available
    needs_pct = table["used_pct"].isna() & table["total_tb"].notna() & table["free_tb"].notna()
    if needs_pct.any():
        derived = (
            (table["total_tb"] - table["free_tb"]) / table["total_tb"] * 100
        ).where(table["total_tb"] > 0)
        table.loc[needs_pct, "used_pct"] = derived[needs_pct].round(2)
    table["warning_level"] = table["warning_level"].map(normalize_severity)
    return table


def normalize_hugepages(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare HugePages rows with consistent used/free percent columns."""

    columns = [
        "cluster",
        "host",
        "hugepages_total",
        "hugepages_free",
        "hugepages_free_pct",
        "hugepages_used_pct",
        "hugepages_allocated_pct_of_ram",
        "transparent_hugepages",
        "warning_level",
    ]
    table = ensure_columns(df, columns)[columns].copy()
    numeric = [
        "hugepages_total",
        "hugepages_free",
        "hugepages_free_pct",
        "hugepages_used_pct",
        "hugepages_allocated_pct_of_ram",
    ]
    for column in numeric:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    needs_used_pct = (
        table["hugepages_used_pct"].isna()
        & table["hugepages_total"].notna()
        & table["hugepages_free"].notna()
    )
    if needs_used_pct.any():
        derived = (
            (table["hugepages_total"] - table["hugepages_free"])
            / table["hugepages_total"]
            * 100
        ).where(table["hugepages_total"] > 0)
        table.loc[needs_used_pct, "hugepages_used_pct"] = derived[needs_used_pct].round(2)
    needs_free_pct = table["hugepages_free_pct"].isna() & table["hugepages_used_pct"].notna()
    if needs_free_pct.any():
        table.loc[needs_free_pct, "hugepages_free_pct"] = (
            100 - table.loc[needs_free_pct, "hugepages_used_pct"]
        )
    table["warning_level"] = table["warning_level"].map(normalize_severity)
    return table


def explode_filesystems(df: pd.DataFrame) -> pd.DataFrame:
    """Build a normalized filesystem table from OS inventory output."""

    rows: list[dict[str, Any]] = []
    if df.empty:
        return pd.DataFrame(
            columns=["cluster", "host", "filesystem", "mount", "used_pct", "warning_level"]
        )
    for _, record in df.iterrows():
        filesystems = record.get("filesystems")
        if filesystems is None or (isinstance(filesystems, float) and pd.isna(filesystems)):
            filesystems = record.get("filesystems_json", [])
        parsed = parse_json_value(filesystems)
        if not isinstance(parsed, list):
            continue
        for filesystem in parsed:
            if isinstance(filesystem, dict):
                rows.append(
                    {
                        "cluster": record.get("cluster"),
                        "host": record.get("host"),
                        **filesystem,
                    }
                )
    table = pd.DataFrame(rows)
    if table.empty:
        return pd.DataFrame(
            columns=["cluster", "host", "filesystem", "mount", "used_pct", "warning_level"]
        )
    table = ensure_columns(
        table,
        [
            "cluster",
            "host",
            "filesystem",
            "mount",
            "mounted_on",
            "use_pct",
            "used_pct",
            "warning_level",
        ],
    )
    if table["used_pct"].isna().all() and not table["use_pct"].isna().all():
        table["used_pct"] = table["use_pct"]
    table["used_pct"] = pd.to_numeric(
        table["used_pct"].astype(str).str.rstrip("%"), errors="coerce"
    )
    table["mount"] = table["mount"].fillna(table["mounted_on"])
    if table["warning_level"].isna().all():
        table["warning_level"] = table["used_pct"].map(severity_from_pct)
    else:
        table["warning_level"] = table["warning_level"].map(normalize_severity)
    table["severity_rank"] = table["warning_level"].map(LEVEL_ORDER).fillna(99)
    return table.sort_values(
        ["severity_rank", "used_pct"], ascending=[True, False], na_position="last"
    )


def normalize_db_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB CPU/IOPS/MBPS AWR history rows for charts."""

    rename_map = {
        "Cluster": "cluster",
        "HOST_NAME": "host_name",
        "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name",
        "BEGIN_TIME": "begin_time",
        "END_TIME": "end_time",
        "TOTAL_IOPS_AVG": "total_iops_avg",
        "TOTAL_IOPS_MAX": "total_iops_max",
        "TOTAL_MBPS_AVG": "total_mbps_avg",
        "TOTAL_MBPS_MAX": "total_mbps_max",
        "CPU_USAGE_PER_SEC_AVG": "cpu_usage_per_sec_avg",
        "CPU_USAGE_PER_SEC_MAX": "cpu_usage_per_sec_max",
        "HOST_CPU_UTIL_PCT_AVG": "host_cpu_util_pct_avg",
        "HOST_CPU_UTIL_PCT_MAX": "host_cpu_util_pct_max",
    }
    table = df.rename(
        columns={
            old: new
            for old, new in rename_map.items()
            if old in df.columns and new not in df.columns
        }
    ).copy()
    identity_columns = [
        "cluster",
        "host_name",
        "db_name",
        "instance_name",
        "begin_time",
        "end_time",
    ]
    numeric_columns = [
        "total_iops_avg",
        "total_iops_max",
        "total_mbps_avg",
        "total_mbps_max",
        "cpu_usage_per_sec_avg",
        "cpu_usage_per_sec_max",
        "host_cpu_util_pct_avg",
        "host_cpu_util_pct_max",
    ]
    columns = identity_columns + numeric_columns
    table = ensure_columns(table, columns)[columns].copy()
    table["begin_time"] = pd.to_datetime(table["begin_time"], errors="coerce")
    table["end_time"] = pd.to_datetime(table["end_time"], errors="coerce")
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def build_db_performance_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Aggregate AWR snapshots by cluster/db/instance/host."""

    group_columns = ["cluster", "db_name", "instance_name", "host_name"]
    result_columns = group_columns + [
        "snapshot_count",
        "begin_time_min",
        "end_time_max",
        "avg_total_iops",
        "max_total_iops",
        "avg_total_mbps",
        "max_total_mbps",
        "avg_db_cpu_per_sec",
        "max_db_cpu_per_sec",
        "avg_host_cpu_util_pct",
        "max_host_cpu_util_pct",
    ]
    normalized = normalize_db_performance(table)
    valid = normalized.dropna(subset=["end_time"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=result_columns)

    valid["begin_time"] = valid["begin_time"].fillna(valid["end_time"])
    summary = (
        valid.groupby(group_columns, dropna=False)
        .agg(
            snapshot_count=("end_time", "size"),
            begin_time_min=("begin_time", "min"),
            end_time_max=("end_time", "max"),
            avg_total_iops=("total_iops_avg", "mean"),
            max_total_iops=("total_iops_max", "max"),
            avg_total_mbps=("total_mbps_avg", "mean"),
            max_total_mbps=("total_mbps_max", "max"),
            avg_db_cpu_per_sec=("cpu_usage_per_sec_avg", "mean"),
            max_db_cpu_per_sec=("cpu_usage_per_sec_max", "max"),
            avg_host_cpu_util_pct=("host_cpu_util_pct_avg", "mean"),
            max_host_cpu_util_pct=("host_cpu_util_pct_max", "max"),
        )
        .reset_index()
    )
    return summary[result_columns]


def normalize_db_memory_history(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB SGA/PGA AWR history rows for charts."""

    rename_map = {
        "Cluster": "cluster",
        "HOST_NAME": "host_name",
        "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name",
        "END_TIME": "end_time",
        "SGA_TARGET_GB": "sga_target_gb",
        "SGA_MAX_SIZE_GB": "sga_max_size_gb",
        "SGA_USED_GB": "sga_used_gb",
        "PGA_AGGREGATE_TARGET_GB": "pga_aggregate_target_gb",
        "PGA_AGGREGATE_LIMIT_GB": "pga_aggregate_limit_gb",
        "PGA_ALLOCATED_GB": "pga_allocated_gb",
        "PGA_USED_GB": "pga_used_gb",
    }
    table = df.rename(
        columns={
            old: new
            for old, new in rename_map.items()
            if old in df.columns and new not in df.columns
        }
    ).copy()
    identity_columns = [
        "cluster",
        "host_name",
        "db_unique_name",
        "db_name",
        "instance_name",
        "end_time",
    ]
    numeric_columns = [
        "sga_target_gb",
        "sga_max_size_gb",
        "sga_used_gb",
        "pga_aggregate_target_gb",
        "pga_aggregate_limit_gb",
        "pga_allocated_gb",
        "pga_used_gb",
    ]
    text_columns = ["collection_status", "warning_severity"]
    columns = identity_columns + numeric_columns + text_columns
    table = ensure_columns(table, columns)[columns].copy()
    table["end_time"] = pd.to_datetime(table["end_time"], errors="coerce")
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["warning_severity"] = table["warning_severity"].map(normalize_severity)
    table["warning_level"] = table["warning_severity"]
    return table


def normalize_db_memory_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize per-instance DB memory analytics summary output."""

    rename_map = {
        "Cluster": "cluster",
        "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name",
        "HOST_NAME": "host_name",
    }
    table = df.rename(
        columns={
            old: new
            for old, new in rename_map.items()
            if old in df.columns and new not in df.columns
        }
    ).copy()
    identity_columns = [
        "cluster",
        "db_unique_name",
        "db_name",
        "instance_name",
        "host_name",
        "begin_time_min",
        "end_time_max",
    ]
    numeric_columns = [
        "snapshot_count",
        "sga_target_gb_max",
        "sga_used_gb_avg",
        "sga_used_gb_max",
        "sga_used_pct_of_target_avg",
        "sga_used_pct_of_target_max",
        "pga_aggregate_target_gb_max",
        "pga_allocated_gb_avg",
        "pga_allocated_gb_max",
        "pga_used_gb_avg",
        "pga_used_gb_max",
        "pga_used_pct_of_target_avg",
        "pga_used_pct_of_target_max",
    ]
    text_columns = ["warning_severity"]
    columns = identity_columns + numeric_columns + text_columns
    table = ensure_columns(table, columns)[columns].copy()
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    for column in ["begin_time_min", "end_time_max"]:
        table[column] = pd.to_datetime(table[column], errors="coerce")
    table["warning_severity"] = table["warning_severity"].map(normalize_severity)
    table["warning_level"] = table["warning_severity"]
    return table
