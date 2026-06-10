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


def _meminfo_mem_total_gb(value: Any) -> float | None:
    parsed = parse_json_value(value)
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get("MemTotal") or parsed.get("mem_total") or parsed.get("memtotal")
    if raw is None:
        return None
    try:
        text = str(raw).strip()
        if not text:
            return None
        # /proc/meminfo MemTotal is typically "16384000 kB"
        token = text.split()[0]
        kb = float(token)
        return round(kb / 1024 / 1024, 2)
    except (TypeError, ValueError, IndexError):
        return None


def os_memory_gb_lookup(os_df: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Build a (cluster, host) -> mem_total_gb lookup from OS inventory rows."""

    if os_df is None or os_df.empty:
        return {}
    lookup: dict[tuple[str, str], float] = {}
    columns = set(os_df.columns)
    for _, record in os_df.iterrows():
        cluster = str(record.get("cluster") or "")
        host = str(record.get("host") or record.get("hostname") or "")
        if not host:
            continue
        meminfo_source = None
        if "meminfo_json" in columns:
            meminfo_source = record.get("meminfo_json")
        if meminfo_source is None and "meminfo" in columns:
            meminfo_source = record.get("meminfo")
        mem_gb = _meminfo_mem_total_gb(meminfo_source)
        if mem_gb is not None:
            lookup[(cluster, host)] = mem_gb
    return lookup


HUGEPAGES_COLUMN_MAP = {
    "Cluster": "cluster",
    "Host": "host",
    "MemTotal": "mem_gb",
    "HP_Size_KB": "hp_size_kb",
    "HP_Total": "hp_total",
    "HP_Free": "hp_free",
    "HP_Rsvd": "hp_rsvd",
    "HP_Surp": "hp_surp",
    "HP_Used": "hp_used",
    "HP_Used_GB": "hp_used_gb",
    "HP_Total_GB": "hp_total_gb",
    "HP_Pct_of_MemTotal": "hp_alloc_pct_ram",
    "THP_Status": "thp_status",
    "Timestamp": "timestamp",
}

HUGEPAGES_LEGACY_MAP = {
    "hugepages_total": "hp_total",
    "hugepages_free": "hp_free",
    "hugepages_rsvd": "hp_rsvd",
    "hugepages_surp": "hp_surp",
    "hugepages_used": "hp_used",
    "hugepagesize_kb": "hp_size_kb",
    "transparent_hugepages": "thp_status",
    "collected_at": "timestamp",
}


def selected_thp_mode(thp_status: Any) -> str:
    """Return the currently-selected THP mode parsed from the raw status."""

    if thp_status is None or (isinstance(thp_status, float) and pd.isna(thp_status)):
        return "unknown"
    text = str(thp_status).strip()
    if not text or text.upper() == "UNKNOWN":
        return "unknown"
    lowered = text.lower()
    if "[always]" in lowered:
        return "always"
    if "[madvise]" in lowered:
        return "madvise"
    if "[never]" in lowered:
        return "never"
    if lowered == "never":
        return "never"
    return "unknown"


def thp_severity(thp_status: Any) -> str:
    """Map a raw THP status string to a severity level."""

    mode = selected_thp_mode(thp_status)
    if mode == "never":
        return "OK"
    if mode == "madvise":
        return "WARNING"
    if mode == "always":
        return "CRITICAL"
    return "INFO"


def hugepages_severity(used_pct: Any, alloc_pct_ram: Any, thp_status: Any) -> str:
    """Combined HugePages severity, honoring used %, allocation, and THP."""

    used = pd.to_numeric(pd.Series([used_pct]), errors="coerce").iloc[0]
    alloc = pd.to_numeric(pd.Series([alloc_pct_ram]), errors="coerce").iloc[0]
    if not pd.isna(used) and float(used) >= 95:
        base = "CRITICAL"
    elif not pd.isna(used) and float(used) >= 80:
        base = "WARNING"
    elif not pd.isna(alloc) and (float(alloc) < 40 or float(alloc) > 80):
        base = "INFO"
    else:
        base = "OK"
    thp_level = thp_severity(thp_status)
    return _max_severity(base, thp_level)


def _max_severity(a: str, b: str) -> str:
    return a if LEVEL_ORDER.get(a, 99) <= LEVEL_ORDER.get(b, 99) else b


def _coerce_hugepages_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename PascalCase / legacy columns to the canonical snake_case schema."""

    if df is None or df.empty:
        return pd.DataFrame(columns=list(HUGEPAGES_COLUMN_MAP.values()))
    renamed = df.rename(
        columns={old: new for old, new in HUGEPAGES_COLUMN_MAP.items() if old in df.columns and new not in df.columns}
    )
    renamed = renamed.rename(
        columns={old: new for old, new in HUGEPAGES_LEGACY_MAP.items() if old in renamed.columns and new not in renamed.columns}
    )
    return renamed


def build_hugepages_node_detail(
    hugepages_df: pd.DataFrame, os_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Build the HugePages node-detail table matching the dashboard layout.

    Columns: cluster, host, mem_gb, hp_total_gb, hp_used_gb, hp_free_gb,
    hp_used_pct, hp_alloc_pct_ram, thp_status, timestamp, severity.
    """

    base_columns = [
        "cluster",
        "host",
        "mem_gb",
        "hp_size_kb",
        "hp_total",
        "hp_free",
        "hp_rsvd",
        "hp_surp",
        "hp_used",
        "hp_total_gb",
        "hp_used_gb",
        "hp_free_gb",
        "hp_used_pct",
        "hp_alloc_pct_ram",
        "thp_status",
        "thp_mode",
        "timestamp",
        "severity",
    ]
    if hugepages_df is None or hugepages_df.empty:
        return pd.DataFrame(columns=base_columns)

    table = _coerce_hugepages_columns(hugepages_df)
    table = ensure_columns(table, base_columns).copy()

    numeric_cols = [
        "mem_gb",
        "hp_size_kb",
        "hp_total",
        "hp_free",
        "hp_used",
        "hp_used_gb",
        "hp_total_gb",
        "hp_alloc_pct_ram",
    ]
    for column in numeric_cols:
        table[column] = pd.to_numeric(table[column], errors="coerce")

    page_size_kb = table["hp_size_kb"].where(table["hp_size_kb"] > 0, 2048).fillna(2048)
    needs_total_gb = table["hp_total_gb"].isna() & table["hp_total"].notna()
    derived_total = (table["hp_total"] * page_size_kb / 1024 / 1024).round()
    table.loc[needs_total_gb, "hp_total_gb"] = derived_total[needs_total_gb]

    derived_free_gb = (table["hp_free"] * page_size_kb / 1024 / 1024).round()
    table["hp_free_gb"] = derived_free_gb

    derived_used_pages = table["hp_total"] - table["hp_free"]
    used_pages = table["hp_used"].where(table["hp_used"].notna(), derived_used_pages)
    needs_used_gb = table["hp_used_gb"].isna()
    derived_used_gb = (used_pages * page_size_kb / 1024 / 1024).round()
    table.loc[needs_used_gb, "hp_used_gb"] = derived_used_gb[needs_used_gb]

    used_pct_series = (used_pages / table["hp_total"] * 100).where(table["hp_total"] > 0)
    table["hp_used_pct"] = used_pct_series.round(2)

    if os_df is not None and not os_df.empty:
        mem_lookup = os_memory_gb_lookup(os_df)
        needs_mem = table["mem_gb"].isna()
        if needs_mem.any():
            fallback = [
                mem_lookup.get((str(c or ""), str(h or "")))
                for c, h in zip(table["cluster"], table["host"])
            ]
            fallback_series = pd.Series(fallback, index=table.index)
            table.loc[needs_mem, "mem_gb"] = fallback_series[needs_mem]

    needs_alloc_pct = table["hp_alloc_pct_ram"].isna() & table["mem_gb"].notna()
    if needs_alloc_pct.any():
        derived = (table["hp_total_gb"] / table["mem_gb"] * 100).where(table["mem_gb"] > 0)
        table.loc[needs_alloc_pct, "hp_alloc_pct_ram"] = derived[needs_alloc_pct].round(1)

    table["thp_mode"] = table["thp_status"].map(selected_thp_mode)
    table["severity"] = [
        hugepages_severity(u, a, t)
        for u, a, t in zip(table["hp_used_pct"], table["hp_alloc_pct_ram"], table["thp_status"])
    ]

    return table[base_columns]


def build_asm_diskgroup_detail(asm_raw: pd.DataFrame) -> pd.DataFrame:
    """Build the ASM diskgroups detail table matching the dashboard layout.

    Columns: cluster, diskgroup_name, type, state, used_tb, free_tb,
    total_tb, used_pct, timestamp.
    """

    if asm_raw is None or asm_raw.empty:
        return pd.DataFrame(
            columns=[
                "cluster",
                "diskgroup_name",
                "type",
                "state",
                "used_tb",
                "free_tb",
                "total_tb",
                "used_pct",
                "timestamp",
                "warning_level",
            ]
        )
    table = ensure_columns(
        asm_raw,
        [
            "cluster",
            "diskgroup_name",
            "type",
            "state",
            "total_tb",
            "free_tb",
            "used_pct",
            "record_type",
            "collected_at",
            "warning_level",
        ],
    ).copy()

    if "record_type" in table.columns:
        table = table[
            (table["record_type"].isna())
            | (table["record_type"].astype(str).str.lower() == "diskgroup")
        ]
    table = table[
        table["diskgroup_name"].notna()
        & (table["diskgroup_name"].astype(str).str.strip() != "")
    ]

    for column in ["total_tb", "free_tb", "used_pct"]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["used_tb"] = (table["total_tb"] - table["free_tb"]).clip(lower=0).round(2)

    needs_pct = table["used_pct"].isna() & table["total_tb"].notna() & table["free_tb"].notna()
    if needs_pct.any():
        derived = (
            (table["total_tb"] - table["free_tb"]) / table["total_tb"] * 100
        ).where(table["total_tb"] > 0)
        table.loc[needs_pct, "used_pct"] = derived[needs_pct].round(2)

    table["timestamp"] = table["collected_at"]
    table["warning_level"] = table["warning_level"].map(normalize_severity)

    return table[
        [
            "cluster",
            "diskgroup_name",
            "type",
            "state",
            "used_tb",
            "free_tb",
            "total_tb",
            "used_pct",
            "timestamp",
            "warning_level",
        ]
    ].reset_index(drop=True)


def normalize_hugepages(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize HugePages rows into canonical snake_case analytics columns.

    Accepts the analytics-ready collector schema (Cluster, Host, MemTotal,
    HP_*, THP_Status, Timestamp) and renames into the snake_case schema used
    by the Dash app. Calculates ``hp_free_gb`` and ``hp_used_pct`` when
    missing from the input.
    """

    canonical_columns = [
        "cluster",
        "host",
        "mem_gb",
        "hp_size_kb",
        "hp_total",
        "hp_free",
        "hp_rsvd",
        "hp_surp",
        "hp_used",
        "hp_used_gb",
        "hp_total_gb",
        "hp_free_gb",
        "hp_alloc_pct_ram",
        "hp_used_pct",
        "thp_status",
        "thp_mode",
        "timestamp",
        "severity",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=canonical_columns)

    table = _coerce_hugepages_columns(df)
    table = ensure_columns(table, canonical_columns).copy()

    numeric = [
        "mem_gb",
        "hp_size_kb",
        "hp_total",
        "hp_free",
        "hp_rsvd",
        "hp_surp",
        "hp_used",
        "hp_used_gb",
        "hp_total_gb",
        "hp_free_gb",
        "hp_alloc_pct_ram",
        "hp_used_pct",
    ]
    for column in numeric:
        table[column] = pd.to_numeric(table[column], errors="coerce")

    page_size_kb = table["hp_size_kb"].where(table["hp_size_kb"] > 0, 2048).fillna(2048)

    needs_hp_used = table["hp_used"].isna() & table["hp_total"].notna() & table["hp_free"].notna()
    if needs_hp_used.any():
        derived = (table["hp_total"] - table["hp_free"]).clip(lower=0)
        table.loc[needs_hp_used, "hp_used"] = derived[needs_hp_used]

    needs_total_gb = table["hp_total_gb"].isna() & table["hp_total"].notna()
    if needs_total_gb.any():
        derived = (table["hp_total"] * page_size_kb / 1024 / 1024).round()
        table.loc[needs_total_gb, "hp_total_gb"] = derived[needs_total_gb]

    needs_used_gb = table["hp_used_gb"].isna() & table["hp_used"].notna()
    if needs_used_gb.any():
        derived = (table["hp_used"] * page_size_kb / 1024 / 1024).round()
        table.loc[needs_used_gb, "hp_used_gb"] = derived[needs_used_gb]

    needs_free_gb = table["hp_free_gb"].isna() & table["hp_free"].notna()
    if needs_free_gb.any():
        derived = (table["hp_free"] * page_size_kb / 1024 / 1024).round()
        table.loc[needs_free_gb, "hp_free_gb"] = derived[needs_free_gb]

    needs_used_pct = (
        table["hp_used_pct"].isna()
        & table["hp_total"].notna()
        & table["hp_used"].notna()
    )
    if needs_used_pct.any():
        derived = (table["hp_used"] / table["hp_total"] * 100).where(table["hp_total"] > 0)
        table.loc[needs_used_pct, "hp_used_pct"] = derived[needs_used_pct].round(2)

    needs_alloc_pct = (
        table["hp_alloc_pct_ram"].isna()
        & table["mem_gb"].notna()
        & table["hp_total_gb"].notna()
    )
    if needs_alloc_pct.any():
        derived = (table["hp_total_gb"] / table["mem_gb"] * 100).where(table["mem_gb"] > 0)
        table.loc[needs_alloc_pct, "hp_alloc_pct_ram"] = derived[needs_alloc_pct].round(1)

    table["thp_mode"] = table["thp_status"].map(selected_thp_mode)
    table["severity"] = [
        hugepages_severity(u, a, t)
        for u, a, t in zip(table["hp_used_pct"], table["hp_alloc_pct_ram"], table["thp_status"])
    ]
    return table[canonical_columns]


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


# ---------------------------------------------------------------------------
# OS inventory: per-host memory and CPU parsing from /proc/meminfo and lscpu.
# ---------------------------------------------------------------------------


def parse_meminfo(value: Any) -> dict[str, Any]:
    """Return a /proc/meminfo dict from a JSON string, dict, or text blob."""

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    if isinstance(value, dict):
        return value
    parsed = parse_json_value(value)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(value, str):
        result: dict[str, Any] = {}
        for line in value.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip()
        return result
    return {}


def _coalesce_meminfo(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("meminfo_json", "meminfo"):
        if key in record:
            parsed = parse_meminfo(record.get(key))
            if parsed:
                return parsed
    return {}


def _meminfo_kb(meminfo: dict[str, Any], key: str) -> float:
    raw = meminfo.get(key)
    if raw is None:
        return float("nan")
    text = str(raw).strip().lower().replace(" kb", "")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def build_os_memory_table(os_inventory: pd.DataFrame) -> pd.DataFrame:
    """Build per-host OS memory snapshot table from ``os_inventory`` output.

    Output columns: cluster, host, hostname, status, mem_total_gb,
    mem_free_gb, mem_available_gb, mem_used_gb, mem_used_pct,
    swap_total_gb, swap_free_gb, swap_used_gb, swap_used_pct, severity.
    """

    columns = [
        "cluster", "host", "hostname", "status",
        "mem_total_gb", "mem_free_gb", "mem_available_gb",
        "mem_used_gb", "mem_used_pct",
        "swap_total_gb", "swap_free_gb", "swap_used_gb", "swap_used_pct",
        "severity",
    ]
    if os_inventory is None or os_inventory.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for _, record in os_inventory.iterrows():
        rec = record.to_dict()
        meminfo = _coalesce_meminfo(rec)
        mem_total_kb = _meminfo_kb(meminfo, "MemTotal")
        mem_free_kb = _meminfo_kb(meminfo, "MemFree")
        mem_available_kb = _meminfo_kb(meminfo, "MemAvailable")
        swap_total_kb = _meminfo_kb(meminfo, "SwapTotal")
        swap_free_kb = _meminfo_kb(meminfo, "SwapFree")
        rows.append({
            "cluster": rec.get("cluster"),
            "host": rec.get("host"),
            "hostname": rec.get("hostname"),
            "status": rec.get("status"),
            "mem_total_gb": mem_total_kb / 1024 / 1024,
            "mem_free_gb": mem_free_kb / 1024 / 1024,
            "mem_available_gb": mem_available_kb / 1024 / 1024,
            "swap_total_gb": swap_total_kb / 1024 / 1024,
            "swap_free_gb": swap_free_kb / 1024 / 1024,
        })
    table = pd.DataFrame(rows)
    # Prefer MemAvailable-based used; fall back to MemFree-based.
    table["mem_used_gb"] = (table["mem_total_gb"] - table["mem_available_gb"]).where(
        table["mem_available_gb"].notna(),
        table["mem_total_gb"] - table["mem_free_gb"],
    )
    table["mem_used_pct"] = (
        (table["mem_used_gb"] / table["mem_total_gb"] * 100)
        .where(table["mem_total_gb"] > 0)
        .round(1)
    )
    table["swap_used_gb"] = table["swap_total_gb"] - table["swap_free_gb"]
    table["swap_used_pct"] = (
        (table["swap_used_gb"] / table["swap_total_gb"] * 100)
        .where(table["swap_total_gb"] > 0)
        .round(1)
    )
    table["severity"] = table["mem_used_pct"].map(severity_from_pct)
    return table[columns]


def _lscpu_dict(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("cpu_json", "cpu"):
        if key not in record:
            continue
        candidate = parse_json_value(record.get(key))
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


def build_os_cpu_table(os_inventory: pd.DataFrame) -> pd.DataFrame:
    """Build per-host OS CPU inventory table from ``os_inventory`` output.

    Output columns: cluster, host, hostname, status, cpus, cores_per_socket,
    sockets, threads_per_core, physical_cores, cpu_model, uptime.
    """

    columns = [
        "cluster", "host", "hostname", "status",
        "cpus", "cores_per_socket", "sockets", "threads_per_core",
        "physical_cores", "cpu_model", "uptime",
    ]
    if os_inventory is None or os_inventory.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for _, record in os_inventory.iterrows():
        rec = record.to_dict()
        cpu_data = _lscpu_dict(rec)
        cpus = _coerce_int(cpu_data.get("CPU(s)") or cpu_data.get("CPUs"))
        cores_per_socket = _coerce_int(
            cpu_data.get("Core(s) per socket") or cpu_data.get("Cores per socket")
        )
        sockets = _coerce_int(cpu_data.get("Socket(s)") or cpu_data.get("Sockets"))
        threads_per_core = _coerce_int(cpu_data.get("Thread(s) per core"))
        physical_cores: int | None
        if cores_per_socket is not None and sockets is not None:
            physical_cores = cores_per_socket * sockets
        else:
            physical_cores = None
        model = cpu_data.get("Model name") or cpu_data.get("Model")
        rows.append({
            "cluster": rec.get("cluster"),
            "host": rec.get("host"),
            "hostname": rec.get("hostname"),
            "status": rec.get("status"),
            "cpus": cpus,
            "cores_per_socket": cores_per_socket,
            "sockets": sockets,
            "threads_per_core": threads_per_core,
            "physical_cores": physical_cores,
            "cpu_model": model,
            "uptime": rec.get("uptime"),
        })
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Inventory: DB resource details, cluster memory rollup, version inventory.
# ---------------------------------------------------------------------------


_DB_RESOURCE_RENAME_MAP = {
    # CSV-style columns (PascalCase) → snake_case used by the dashboard.
    "Cluster": "cluster",
    "HOST_NAME": "host_name",
    "DB_NAME": "db_name",
    "DB_ROLE": "db_role",
    "OPEN_MODE": "open_mode",
    "VERSION": "version",
    "RAC_ENABLED": "rac_enabled",
    "INST_COUNT": "inst_count",
    "SGA_TARGET_GB": "sga_target_gb",
    "PGA_AGGR_TARGET_GB": "pga_aggr_target_gb",
    "SGA_MAX_SIZE_GB": "sga_max_size_gb",
    "PGA_AGGR_LIMIT_GB": "pga_aggr_limit_gb",
    "PROCESSES": "processes",
    "CPU_COUNT": "cpu_count",
    "DB_SIZE_GB": "db_size_gb",
    "USED_DB_SIZE_GB": "used_db_size_gb",
    "DB_USED_PCT": "db_used_pct",
    "Collected_At": "collected_at",
}


def normalize_db_resource_details(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the per-DB resource detail snapshot for the Dash app.

    Accepts both the JSON output (already snake_case) and the CSV output
    (PascalCase). Numeric columns are coerced; ``db_used_pct`` is derived
    when missing but ``db_size_gb`` and ``used_db_size_gb`` are present.
    A ``warning_level`` column is derived from ``db_used_pct`` so the
    standard severity styling applies.
    """

    identity_columns = [
        "cluster", "host", "host_name", "db_unique_name", "db_name",
        "db_role", "open_mode", "version", "rac_enabled", "oracle_home",
        "oracle_sid", "size_source", "collection_status", "collected_at",
    ]
    numeric_columns = [
        "inst_count", "cpu_count", "processes",
        "sga_target_gb", "sga_max_size_gb",
        "pga_aggr_target_gb", "pga_aggr_limit_gb",
        "db_size_gb", "used_db_size_gb", "db_used_pct",
    ]
    columns = identity_columns + numeric_columns + ["warning_level"]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    table = df.rename(
        columns={
            old: new
            for old, new in _DB_RESOURCE_RENAME_MAP.items()
            if old in df.columns and new not in df.columns
        }
    ).copy()
    table = ensure_columns(table, columns).copy()
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")

    # Derive db_used_pct when the collector did not include it.
    needs_pct = (
        table["db_used_pct"].isna()
        & table["db_size_gb"].notna()
        & table["used_db_size_gb"].notna()
    )
    if needs_pct.any():
        derived = (
            (table["used_db_size_gb"] / table["db_size_gb"]) * 100
        ).where(table["db_size_gb"] > 0)
        table.loc[needs_pct, "db_used_pct"] = derived[needs_pct].round(2)

    table["warning_level"] = table["db_used_pct"].map(severity_from_pct)
    return table[columns]


_DB_MEM_CLUSTER_RENAME_MAP = {
    "Cluster": "cluster",
}


def normalize_db_memory_cluster_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the cluster-level DB memory rollup output.

    The collector writes ``db_memory_cluster_summary.{json,csv}``. This
    helper renames Cluster→cluster, coerces numerics, and returns the
    canonical columns expected by the dashboard.
    """

    columns = [
        "cluster", "database_count", "instance_count",
        "avg_sga_used_gb", "max_sga_used_gb",
        "total_latest_sga_used_gb",
        "total_latest_pga_used_gb",
        "total_latest_pga_allocated_gb",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    table = df.rename(
        columns={
            old: new
            for old, new in _DB_MEM_CLUSTER_RENAME_MAP.items()
            if old in df.columns and new not in df.columns
        }
    ).copy()
    table = ensure_columns(table, columns).copy()
    for column in columns:
        if column == "cluster":
            continue
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table[columns]


def normalize_version_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the per-host image / GI patch inventory output.

    Reads ``version_inventory.{json,csv}`` (already snake_case in JSON).
    Returns a stable column order useful for the Fleet Inventory page.
    """

    columns = [
        "cluster", "host", "address", "node_type",
        "image_version", "exadata_software_version", "image_status",
        "image_activated", "kernel_version",
        "gi_active_version", "gi_release_version",
        "gi_release_patch_string", "gi_release_patch_level",
        "collection_status", "collected_at",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    table = ensure_columns(df, columns).copy()
    return table[columns]


def build_cluster_version_drift(version_df: pd.DataFrame) -> pd.DataFrame:
    """Return per-cluster image/GI patch drift indicators.

    Output columns: cluster, host_count, image_versions, gi_patch_strings,
    image_drift, gi_patch_drift, severity. ``*_drift`` is True when more
    than one distinct value is observed on that cluster.
    """

    drift_columns = [
        "cluster", "host_count",
        "image_versions", "gi_patch_strings",
        "image_drift", "gi_patch_drift", "severity",
    ]
    if version_df is None or version_df.empty:
        return pd.DataFrame(columns=drift_columns)

    df = normalize_version_inventory(version_df)
    rows: list[dict[str, Any]] = []
    for cluster, group in df.groupby(df["cluster"].fillna(""), dropna=False):
        if not str(cluster).strip():
            continue
        image_set = sorted(
            {str(v).strip() for v in group["image_version"].dropna() if str(v).strip()}
        )
        gi_set = sorted(
            {
                str(v).strip()
                for v in group["gi_release_patch_string"].dropna()
                if str(v).strip()
            }
        )
        image_drift = len(image_set) > 1
        gi_drift = len(gi_set) > 1
        severity = "WARNING" if (image_drift or gi_drift) else "OK"
        rows.append({
            "cluster": cluster,
            "host_count": int(len(group)),
            "image_versions": ", ".join(image_set) or "—",
            "gi_patch_strings": ", ".join(gi_set) or "—",
            "image_drift": image_drift,
            "gi_patch_drift": gi_drift,
            "severity": severity,
        })
    return pd.DataFrame(rows, columns=drift_columns)


# ---------------------------------------------------------------------------
# Storage-cell inventory.
# ---------------------------------------------------------------------------


def normalize_cell_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize successful cell inventory rows for the Dash page.

    Renames the PascalCase cell columns to snake_case, coerces GB/count
    numerics, and derives flash-cache / hard-disk / flash-disk TB columns.
    """

    rename_map = {
        "Cluster": "cluster",
        "CELL_NAME": "cell_name",
        "CELL_VERSION": "cell_version",
        "CELL_RELEASE_VERSION": "cell_release_version",
        "MAKE_MODEL": "make_model",
        "STATUS": "status",
        "CPU_COUNT": "cpu_count",
        "FLASH_CACHE_GB": "flash_cache_gb",
        "FLASH_CACHE_MODE": "flash_cache_mode",
        "HARD_DISK_GB": "hard_disk_gb",
        "FLASH_DISK_GB": "flash_disk_gb",
        "HARD_DISK_COUNT": "hard_disk_count",
        "FLASH_DISK_COUNT": "flash_disk_count",
    }
    columns = [
        "cluster", "source_host", "cell_name", "cell_version", "cell_release_version",
        "make_model", "status", "cpu_count",
        "flash_cache_gb", "flash_cache_tb", "flash_cache_mode",
        "hard_disk_gb", "hard_disk_tb", "hard_disk_count",
        "flash_disk_gb", "flash_disk_tb", "flash_disk_count",
        "cell_access_method", "cell_target",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)

    table = df.rename(
        columns={old: new for old, new in rename_map.items() if old in df.columns and new not in df.columns}
    ).copy()
    table = ensure_columns(table, columns).copy()
    for col in ("cpu_count", "flash_cache_gb", "hard_disk_gb", "flash_disk_gb",
                "hard_disk_count", "flash_disk_count"):
        table[col] = pd.to_numeric(table[col], errors="coerce")
    for gb_col, tb_col in (
        ("flash_cache_gb", "flash_cache_tb"),
        ("hard_disk_gb", "hard_disk_tb"),
        ("flash_disk_gb", "flash_disk_tb"),
    ):
        table[tb_col] = (table[gb_col] / 1024).round(2)
    return table[columns]


def normalize_cell_inventory_errors(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize failed cell-access rows for the Dash error table."""

    rename_map = {"Cluster": "cluster"}
    columns = [
        "cluster", "source_host", "cell_access_method", "cell_target",
        "cell_user_attempted", "error_category", "collection_error",
        "dcli_available", "cell_group_file_used", "cell_hosts_discovered",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=columns)
    table = df.rename(
        columns={old: new for old, new in rename_map.items() if old in df.columns and new not in df.columns}
    ).copy()
    table = ensure_columns(table, columns).copy()
    table["warning_level"] = "CRITICAL"
    return table[columns + ["warning_level"]]
