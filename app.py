"""Local Streamlit dashboard for Exadata Resource Intelligence Collector output.

The dashboard intentionally reads only local files from ``output/``. It does not
open SSH connections, call collectors, or contact Exadata hosts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

OUTPUT_DIR = Path("output")
HEALTH_LEVELS = ["CRITICAL", "WARNING", "INFO", "OK"]
LEVEL_COLORS = {
    "CRITICAL": "#d92d20",
    "WARNING": "#f59e0b",
    "INFO": "#2563eb",
    "OK": "#16a34a",
}
LEVEL_BACKGROUNDS = {
    "CRITICAL": "#fff1f0",
    "WARNING": "#fffbeb",
    "INFO": "#eff6ff",
    "OK": "#f0fdf4",
}
LEVEL_ORDER = {level: index for index, level in enumerate(HEALTH_LEVELS)}
NAVIGATION = [
    "Executive Cockpit",
    "ASM Capacity",
    "HugePages",
    "Host Inventory",
    "Version Inventory",
    "DB Inventory",
    "DB Performance",
    "CPU Analytics",
    "IOPS Analytics",
    "DB Memory History",
    "Memory Analytics",
    "Raw Data Explorer",
]


st.set_page_config(
    page_title="Exadata Resource Cockpit",
    page_icon="🛰️",
    layout="wide",
)


st.markdown(
    """
    <style>
    .block-container {padding-top: 1.4rem;}
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
    }
    .cockpit-card {
        border-radius: 18px;
        color: #ffffff;
        min-height: 116px;
        padding: 18px;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.12);
    }
    .cockpit-card .label {
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: .05em;
        opacity: .92;
        text-transform: uppercase;
    }
    .cockpit-card .value {
        font-size: 2rem;
        font-weight: 800;
        margin-top: .45rem;
    }
    .critical-card {background: linear-gradient(135deg, #b42318, #f04438);}
    .warning-card {background: linear-gradient(135deg, #b54708, #f59e0b);}
    .info-card {background: linear-gradient(135deg, #1d4ed8, #3b82f6);}
    .ok-card {background: linear-gradient(135deg, #087443, #22c55e);}
    .neutral-card {background: linear-gradient(135deg, #1e3a8a, #2563eb);}
    .section-panel {
        border: 1px solid #e5e7eb;
        border-radius: 18px;
        padding: 1rem;
        background: #ffffff;
        box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _preferred_output_path(stem: str) -> Path | None:
    """Return the preferred JSON/CSV output path for a collector output stem."""

    for suffix in (".json", ".csv"):
        candidate = OUTPUT_DIR / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


@st.cache_data(show_spinner=False)
def read_output(stem: str) -> tuple[pd.DataFrame, Path | None]:
    """Read an output JSON/CSV file into a dataframe."""

    path = _preferred_output_path(stem)
    if path is None:
        return pd.DataFrame(), None
    return read_file(path), path


@st.cache_data(show_spinner=False)
def read_file(path: Path) -> pd.DataFrame:
    """Read a JSON or CSV file into a dataframe."""

    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    with path.open(encoding="utf-8") as json_file:
        payload = json.load(json_file)

    if isinstance(payload, list):
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        return pd.json_normalize(payload)
    return pd.DataFrame({"value": [payload]})


def read_raw_json(path: Path) -> Any:
    """Read JSON payload for the raw explorer."""

    with path.open(encoding="utf-8") as json_file:
        return json.load(json_file)


def parse_json_value(value: Any) -> Any:
    """Parse a nested JSON string when collector CSV output stores JSON text."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return a dataframe with all requested columns present."""

    output = df.copy()
    for column in columns:
        if column not in output.columns:
            output[column] = pd.NA
    return output


def normalize_severity(value: Any) -> str:
    """Normalize memory and health severity values to supported dashboard levels."""

    level = str(value).upper().strip() if pd.notna(value) else "OK"
    return level if level in HEALTH_LEVELS else "OK"


def normalize_warning_level(value: Any) -> str:
    """Backward-compatible alias for normalizing collector warning levels."""

    return normalize_severity(value)


def warning_from_pct(value: Any, critical: float = 90.0, warning: float = 80.0) -> str:
    """Derive a warning level from a used percentage value."""

    pct = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(pct):
        return "OK"
    if float(pct) >= critical:
        return "CRITICAL"
    if float(pct) >= warning:
        return "WARNING"
    return "OK"


def warning_cell_style(column: str, first_column: str, level: str) -> str:
    """Return the cell style for a warning level and column position."""

    background = LEVEL_BACKGROUNDS.get(level, "")
    if not background:
        return ""
    if column == first_column:
        border = LEVEL_COLORS.get(level, "")
        return f"background-color: {background}; border-left: 4px solid {border}"
    return f"background-color: {background}"


def apply_warning_style(df: pd.DataFrame) -> pd.DataFrame:
    """Return a dataframe style map for warning levels."""

    if "warning_level" not in df.columns:
        return pd.DataFrame("", index=df.index, columns=df.columns)

    first_column = df.columns[0]
    styles = []
    for _, row in df.iterrows():
        level = normalize_warning_level(row.get("warning_level"))
        styles.append(
            [
                warning_cell_style(column, first_column, level)
                for column in df.columns
            ]
        )
    return pd.DataFrame(styles, index=df.index, columns=df.columns)


def show_source(path: Path | None) -> None:
    """Show source file information for a dashboard section."""

    if path is None:
        st.info("No local output file found for this section yet.")
    else:
        st.caption(f"Source: {path}")


def card(label: str, value: Any, state: str = "neutral") -> None:
    """Render a color-coded KPI card."""

    css_class = {
        "CRITICAL": "critical-card",
        "WARNING": "warning-card",
        "INFO": "info-card",
        "OK": "ok-card",
    }.get(state, "neutral-card")
    st.markdown(
        f"""
        <div class="cockpit-card {css_class}">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def apply_global_filters(df: pd.DataFrame, filters: dict[str, list[str]]) -> pd.DataFrame:
    """Apply global sidebar filters where the target columns exist."""

    filtered = df.copy()
    aliases = {"host": "host_name", "warning_level": "warning_severity"}
    for column, selected in filters.items():
        target = column if column in filtered.columns else aliases.get(column)
        if selected and target in filtered.columns:
            filtered = filtered[filtered[target].astype(str).isin(selected)]
    return filtered


def normalize_health(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare health summary rows for cockpit views."""

    table = ensure_columns(df, ["cluster", "host", "warning_level", "category", "message", "recommendation"])
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    table["severity_rank"] = table["warning_level"].map(LEVEL_ORDER).fillna(99)
    return table.sort_values(["severity_rank", "cluster", "host"], na_position="last")


def normalize_asm(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare ASM rows for summaries, charts, and filters."""

    columns = ["cluster", "host", "diskgroup_name", "total_tb", "free_tb", "usable_tb", "used_pct", "warning_level"]
    table = ensure_columns(df, columns)[columns].copy()
    for column in ["total_tb", "free_tb", "usable_tb", "used_pct"]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    return table


def normalize_hugepages(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare HugePages rows and a consistent free percentage column."""

    columns = [
        "cluster",
        "host",
        "hugepages_total",
        "hugepages_free",
        "hugepages_free_pct",
        "hugepages_used_pct",
        "warning_level",
    ]
    table = ensure_columns(df, columns)[columns].copy()
    for column in ["hugepages_total", "hugepages_free", "hugepages_free_pct", "hugepages_used_pct"]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    return table


def normalize_db_resources(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare successful DB resource detail rows for KPIs, filters, and charts."""

    columns = [
        "cluster",
        "db_unique_name",
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
        "oracle_home",
        "oracle_sid",
        "host_name",
        "host",
        "collection_status",
    ]
    table = df.copy()
    rename_map = {
        "Cluster": "cluster",
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
        "HOST_NAME": "host_name",
    }
    table = table.rename(columns={old: new for old, new in rename_map.items() if old in table.columns and new not in table.columns})
    table = ensure_columns(table, columns)[columns].copy()
    for column in [
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
    ]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    if table["db_used_pct"].isna().all():
        table["db_used_pct"] = (table["used_db_size_gb"] / table["db_size_gb"] * 100).round(2).where(table["db_size_gb"] > 0)
    table["rac_enabled"] = table["rac_enabled"].astype(str).str.upper().replace({"NAN": ""})
    return table


def dedupe_db_resources(table: pd.DataFrame) -> pd.DataFrame:
    """Keep the first successful row per cluster + db_unique_name for RAC-safe totals."""

    if table.empty:
        return table
    dedupe = table.copy()
    dedupe["_dedupe_key"] = dedupe["db_unique_name"].where(dedupe["db_unique_name"].notna() & (dedupe["db_unique_name"].astype(str).str.strip() != ""), dedupe["db_name"])
    dedupe = dedupe.sort_index().drop_duplicates(subset=["cluster", "_dedupe_key"], keep="first")
    return dedupe.drop(columns=["_dedupe_key"], errors="ignore")


def normalize_db_resource_errors(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB resource skipped/failed rows for display."""

    columns = [
        "cluster",
        "host",
        "db_unique_name",
        "oracle_sid",
        "collection_status",
        "error_category",
        "collection_error",
        "sql_returncode",
        "mapping_source",
    ]
    return ensure_columns(df, columns)[columns].copy()


def explode_filesystems(df: pd.DataFrame) -> pd.DataFrame:
    """Build a normalized filesystem table from OS inventory output."""

    rows: list[dict[str, Any]] = []
    for _, record in df.iterrows():
        filesystems = record.get("filesystems", record.get("filesystems_json", []))
        parsed = parse_json_value(filesystems)
        if not isinstance(parsed, list):
            continue
        for filesystem in parsed:
            if isinstance(filesystem, dict):
                row = {
                    "cluster": record.get("cluster"),
                    "host": record.get("host"),
                    **filesystem,
                }
                rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table

    table = ensure_columns(table, ["cluster", "host", "filesystem", "mount", "mounted_on", "used_pct", "use_pct", "warning_level"])
    if table["used_pct"].isna().all() and not table["use_pct"].isna().all():
        table["used_pct"] = table["use_pct"]
    table["used_pct"] = pd.to_numeric(table["used_pct"].astype(str).str.rstrip("%"), errors="coerce")
    table["mount"] = table["mount"].fillna(table["mounted_on"])
    if table["warning_level"].isna().all():
        table["warning_level"] = table["used_pct"].map(warning_from_pct)
    else:
        table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    table["severity_rank"] = table["warning_level"].map(LEVEL_ORDER).fillna(99)
    return table.sort_values(["severity_rank", "used_pct"], ascending=[True, False], na_position="last")



def normalize_db_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB CPU/IOPS AWR history rows for charts."""

    rename_map = {
        "Cluster": "cluster", "HOST_NAME": "host_name", "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name", "BEGIN_TIME": "begin_time",
        "END_TIME": "end_time",
        "TOTAL_IOPS_AVG": "total_iops_avg", "TOTAL_IOPS_MAX": "total_iops_max",
        "TOTAL_MBPS_AVG": "total_mbps_avg", "TOTAL_MBPS_MAX": "total_mbps_max",
        "CPU_USAGE_PER_SEC_AVG": "cpu_usage_per_sec_avg",
        "CPU_USAGE_PER_SEC_MAX": "cpu_usage_per_sec_max",
        "HOST_CPU_UTIL_PCT_AVG": "host_cpu_util_pct_avg",
        "HOST_CPU_UTIL_PCT_MAX": "host_cpu_util_pct_max",
    }
    table = df.rename(columns={old: new for old, new in rename_map.items() if old in df.columns and new not in df.columns}).copy()
    identity_columns = [
        "cluster", "host_name", "db_name", "instance_name", "begin_time",
        "end_time",
    ]
    numeric_columns = [
        "total_iops_avg", "total_iops_max", "total_mbps_avg", "total_mbps_max",
        "cpu_usage_per_sec_avg", "cpu_usage_per_sec_max",
        "host_cpu_util_pct_avg", "host_cpu_util_pct_max",
    ]
    columns = identity_columns + numeric_columns
    table = ensure_columns(table, columns)[columns].copy()
    table["begin_time"] = pd.to_datetime(table["begin_time"], errors="coerce")
    table["end_time"] = pd.to_datetime(table["end_time"], errors="coerce")
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def build_performance_summary(table: pd.DataFrame) -> pd.DataFrame:
    """Aggregate valid DB performance snapshots by database instance and host."""

    group_columns = ["cluster", "db_name", "instance_name", "host_name"]
    result_columns = group_columns + [
        "snapshot_count", "begin_time_min", "end_time_max",
        "avg_total_iops", "max_total_iops", "avg_total_mbps",
        "max_total_mbps", "avg_db_cpu_per_sec", "max_db_cpu_per_sec",
        "avg_host_cpu_util_pct", "max_host_cpu_util_pct",
    ]
    normalized = normalize_db_performance(table)
    valid = normalized.dropna(subset=["end_time"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=result_columns)

    valid["begin_time"] = valid["begin_time"].fillna(valid["end_time"])
    summary = valid.groupby(group_columns, dropna=False).agg(
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
    ).reset_index()
    return summary[result_columns]


def cpu_performance_severity(host_cpu_util_pct_max: Any) -> str:
    """Classify host CPU utilization for the CPU analytics risk table."""

    value = pd.to_numeric(pd.Series([host_cpu_util_pct_max]), errors="coerce").iloc[0]
    if pd.notna(value) and float(value) >= 90:
        return "CRITICAL"
    if pd.notna(value) and float(value) >= 80:
        return "WARNING"
    return "INFO"


def iops_performance_severity(
    max_total_iops: Any,
    max_total_mbps: Any,
    warning_iops: float = 5000,
    critical_iops: float = 10000,
    warning_mbps: float = 500,
    critical_mbps: float = 1000,
) -> str:
    """Classify I/O risk against page-local IOPS and throughput thresholds."""

    iops = pd.to_numeric(pd.Series([max_total_iops]), errors="coerce").iloc[0]
    mbps = pd.to_numeric(pd.Series([max_total_mbps]), errors="coerce").iloc[0]
    if (pd.notna(iops) and float(iops) >= critical_iops) or (
        pd.notna(mbps) and float(mbps) >= critical_mbps
    ):
        return "CRITICAL"
    if (pd.notna(iops) and float(iops) >= warning_iops) or (
        pd.notna(mbps) and float(mbps) >= warning_mbps
    ):
        return "WARNING"
    return "OK"


def normalize_db_memory_history(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB SGA/PGA AWR history rows for charts and warning views."""

    rename_map = {
        "Cluster": "cluster", "HOST_NAME": "host_name", "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name", "END_TIME": "end_time",
        "SGA_TARGET_GB": "sga_target_gb", "SGA_MAX_SIZE_GB": "sga_max_size_gb",
        "SGA_USED_GB": "sga_used_gb", "PGA_AGGREGATE_TARGET_GB": "pga_aggregate_target_gb",
        "PGA_AGGREGATE_LIMIT_GB": "pga_aggregate_limit_gb", "PGA_ALLOCATED_GB": "pga_allocated_gb",
        "PGA_USED_GB": "pga_used_gb", "PGA_FREEABLE_GB": "pga_freeable_gb",
        "PGA_MAX_ALLOCATED_GB": "pga_max_allocated_gb",
        "SGA_FIXED_GB": "sga_fixed_gb", "SGA_REDO_GB": "sga_redo_gb",
        "SGA_BUFFER_CACHE_GB": "sga_buffer_cache_gb", "SGA_SHARED_POOL_GB": "sga_shared_pool_gb",
        "SGA_LARGE_POOL_GB": "sga_large_pool_gb", "SGA_JAVA_POOL_GB": "sga_java_pool_gb",
        "SGA_STREAMS_POOL_GB": "sga_streams_pool_gb", "SGA_SHARED_IO_POOL_GB": "sga_shared_io_pool_gb",
        "SGA_INMEMORY_AREA_GB": "sga_inmemory_area_gb", "SGA_RESULT_CACHE_GB": "sga_result_cache_gb",
        "SGA_OTHER_GB": "sga_other_gb",
    }
    table = df.rename(columns={old: new for old, new in rename_map.items() if old in df.columns and new not in df.columns}).copy()
    identity_columns = ["cluster", "host_name", "db_unique_name", "db_name", "instance_name", "end_time"]
    numeric_columns = [
        "sga_target_gb", "sga_max_size_gb", "sga_used_gb", "pga_aggregate_target_gb",
        "pga_aggregate_limit_gb", "pga_allocated_gb", "pga_used_gb", "pga_freeable_gb",
        "pga_max_allocated_gb", "sga_fixed_gb", "sga_redo_gb", "sga_buffer_cache_gb",
        "sga_shared_pool_gb", "sga_large_pool_gb", "sga_java_pool_gb", "sga_streams_pool_gb",
        "sga_shared_io_pool_gb", "sga_inmemory_area_gb", "sga_result_cache_gb", "sga_other_gb",
    ]
    text_columns = [
        "collection_status", "warning_severity", "warnings", "info_warnings",
        "warning_warnings", "critical_warnings",
    ]
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
        "Cluster": "cluster", "DB_NAME": "db_name", "INSTANCE_NAME": "instance_name",
        "HOST_NAME": "host_name",
    }
    table = df.rename(columns={old: new for old, new in rename_map.items() if old in df.columns and new not in df.columns}).copy()
    identity_columns = [
        "cluster", "db_unique_name", "db_name", "instance_name", "host_name",
        "begin_time_min", "end_time_max",
    ]
    numeric_columns = [
        "snapshot_count", "sga_target_gb_max", "sga_max_size_gb_max", "sga_used_gb_avg",
        "sga_used_gb_max", "sga_used_pct_of_target_avg", "sga_used_pct_of_target_max",
        "sga_growth_headroom_gb", "sga_buffer_cache_gb_avg", "sga_buffer_cache_gb_max",
        "sga_shared_pool_gb_avg", "sga_shared_pool_gb_max", "sga_large_pool_gb_avg",
        "sga_other_gb_avg", "sga_other_gb_max", "pga_aggregate_target_gb_max",
        "pga_aggregate_limit_gb_max", "pga_allocated_gb_avg", "pga_allocated_gb_max",
        "pga_used_gb_avg", "pga_used_gb_max", "pga_used_pct_of_target_avg",
        "pga_used_pct_of_target_max", "pga_max_allocated_gb_max", "warning_count",
    ]
    text_columns = [
        "warnings", "info_warnings", "warning_warnings", "critical_warnings", "warning_severity",
    ]
    columns = identity_columns + numeric_columns + text_columns
    table = ensure_columns(table, columns)[columns].copy()
    for column in numeric_columns:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    for column in ["begin_time_min", "end_time_max"]:
        table[column] = pd.to_datetime(table[column], errors="coerce")
    table["warning_severity"] = table["warning_severity"].map(normalize_severity)
    table["warning_level"] = table["warning_severity"]
    return table


def _normalize_optional_memory_analytics(
    df: pd.DataFrame, numeric_columns: list[str]
) -> pd.DataFrame:
    """Normalize shared identity, numeric, and severity fields in optional outputs."""

    if df.empty:
        return pd.DataFrame()
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
    for column in numeric_columns:
        if column in table.columns:
            table[column] = pd.to_numeric(table[column], errors="coerce")
    if "warning_severity" in table.columns:
        table["warning_severity"] = table["warning_severity"].map(
            normalize_warning_level
        )
        table["warning_level"] = table["warning_severity"]
    return table


def normalize_memory_capacity_top_consumers(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional top memory consumer analytics output."""

    return _normalize_optional_memory_analytics(
        df,
        [
            "snapshot_count", "sga_max_size_gb_max", "sga_used_gb_avg",
            "sga_used_gb_max", "pga_aggregate_target_gb_max",
            "pga_allocated_gb_avg", "pga_allocated_gb_max", "pga_used_gb_max",
        ],
    )


def normalize_memory_warning_report(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional memory warning report output."""

    return _normalize_optional_memory_analytics(
        df,
        [
            "warning_count", "sga_growth_headroom_gb",
            "pga_used_pct_of_target_max", "pga_allocated_gb_max",
            "pga_aggregate_target_gb_max",
        ],
    )


def normalize_memory_rightsizing_candidates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional memory rightsizing recommendation output."""

    return _normalize_optional_memory_analytics(
        df, ["current_value", "observed_peak"]
    )


def normalize_memory_cluster_rollup(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize optional cluster-level memory rollup output."""

    return _normalize_optional_memory_analytics(
        df,
        [
            "database_count", "instance_count", "db_instances",
            "total_sga_max_size_gb", "total_sga_used_gb_max",
            "total_pga_target_gb", "total_pga_allocated_gb_max",
            "critical_count", "warning_count", "info_count",
        ],
    )


def build_memory_cluster_rollup(summary: pd.DataFrame) -> pd.DataFrame:
    """Build cluster memory totals and finding counts from a memory summary frame."""

    if summary.empty:
        return pd.DataFrame()
    table = normalize_db_memory_summary(summary)
    table = ensure_columns(
        table,
        [
            "cluster", "db_unique_name", "db_name", "instance_name", "sga_used_gb_max",
            "pga_allocated_gb_max", "sga_max_size_gb_max", "pga_aggregate_target_gb_max",
            "warning_severity",
        ],
    )
    database_identity = table["db_unique_name"].fillna(table["db_name"])
    table = table.assign(_database_identity=database_identity)
    rollup = table.groupby("cluster", dropna=False).agg(
        database_count=("_database_identity", "nunique"),
        instance_count=("instance_name", "nunique"),
        total_sga_used_gb_max=("sga_used_gb_max", "sum"),
        total_pga_allocated_gb_max=("pga_allocated_gb_max", "sum"),
        total_sga_max_size_gb=("sga_max_size_gb_max", "sum"),
        total_pga_target_gb=("pga_aggregate_target_gb_max", "sum"),
    ).reset_index()
    # Keep the legacy helper column for callers that used the original fallback schema.
    rollup["db_instances"] = rollup["instance_count"]
    for severity in ["CRITICAL", "WARNING", "INFO"]:
        counts = table[table["warning_severity"] == severity].groupby("cluster", dropna=False).size()
        rollup[f"{severity.lower()}_count"] = rollup["cluster"].map(counts).fillna(0).astype(int)
    return rollup


def build_global_filters() -> tuple[str, dict[str, list[str]]]:
    """Render sidebar navigation, refresh, and global filters."""

    st.sidebar.title("🛰️ Exadata Cockpit")
    if st.sidebar.button("🔄 Refresh local output"):
        st.cache_data.clear()
        st.rerun()

    page = st.sidebar.radio("Navigation", NAVIGATION, index=0)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Global filters")

    datasets = [
        normalize_health(read_output("health_summary")[0]),
        normalize_asm(read_output("asm_diskgroups")[0]),
        normalize_hugepages(read_output("hugepages")[0]),
        normalize_db_resources(read_output("db_resource_details")[0]),
        normalize_db_performance(read_output("db_performance")[0]).rename(columns={"host_name": "host"}),
        normalize_db_memory_history(read_output("db_memory_history")[0]).rename(columns={"host_name": "host"}),
        normalize_db_memory_summary(read_output("db_memory_history_summary")[0]).rename(columns={"host_name": "host"}),
        ensure_columns(read_output("os_inventory")[0], ["cluster", "host"]),
        normalize_health(ensure_columns(read_output("version_inventory")[0], ["cluster", "host", "warning_level"])),
    ]
    combined = pd.concat(datasets, ignore_index=True, sort=False) if datasets else pd.DataFrame()

    filters: dict[str, list[str]] = {}
    for column, label in [("cluster", "Cluster"), ("host", "Host"), ("warning_level", "Warning level")]:
        if column in combined.columns and not combined.empty:
            values = sorted({str(value) for value in combined[column].dropna().tolist() if str(value).strip()})
        else:
            values = []
        filters[column] = st.sidebar.multiselect(label, values, default=[])

    st.sidebar.caption("Local mode only: dashboard reads output/ JSON and CSV files and never opens SSH connections.")
    return page, filters


def render_kpis(health: pd.DataFrame, asm: pd.DataFrame, hugepages: pd.DataFrame, db_resources: pd.DataFrame, db_errors: pd.DataFrame) -> None:
    """Render top executive KPI cards."""

    total_clusters = len({str(value) for value in pd.concat([health.get("cluster", pd.Series(dtype=object)), asm.get("cluster", pd.Series(dtype=object)), hugepages.get("cluster", pd.Series(dtype=object))]).dropna()})
    total_hosts = len({str(value) for value in pd.concat([health.get("host", pd.Series(dtype=object)), asm.get("host", pd.Series(dtype=object)), hugepages.get("host", pd.Series(dtype=object))]).dropna()})
    critical_issues = int((health["warning_level"] == "CRITICAL").sum()) if "warning_level" in health.columns else 0
    warning_issues = int((health["warning_level"] == "WARNING").sum()) if "warning_level" in health.columns else 0
    asm_total_tb = asm["total_tb"].sum(skipna=True) if "total_tb" in asm.columns else 0
    asm_free_tb = asm["free_tb"].sum(skipna=True) if "free_tb" in asm.columns else 0
    hp_critical = int((hugepages["warning_level"] == "CRITICAL").sum()) if "warning_level" in hugepages.columns else 0
    db_deduped = dedupe_db_resources(db_resources)
    total_dbs = len(db_deduped)
    primary_dbs = int(db_deduped["db_role"].astype(str).str.upper().str.contains("PRIMARY", na=False).sum()) if "db_role" in db_deduped.columns else 0
    standby_dbs = int(db_deduped["db_role"].astype(str).str.upper().str.contains("STANDBY", na=False).sum()) if "db_role" in db_deduped.columns else 0
    db_warnings = int(health[(health.get("category", pd.Series(dtype=object)).astype(str) == "DB_RESOURCE") & (health.get("warning_level", pd.Series(dtype=object)).isin(["CRITICAL", "WARNING"]))].shape[0]) if not health.empty else 0
    db_failures = int((db_errors.get("collection_status", pd.Series(dtype=object)).astype(str).str.lower() == "failed").sum()) if not db_errors.empty else 0

    cols = st.columns(12)
    with cols[0]:
        card("Total clusters", total_clusters, "neutral")
    with cols[1]:
        card("Total hosts", total_hosts, "neutral")
    with cols[2]:
        card("Critical issues", critical_issues, "CRITICAL" if critical_issues else "OK")
    with cols[3]:
        card("Warning issues", warning_issues, "WARNING" if warning_issues else "OK")
    with cols[4]:
        card("ASM total TB", f"{asm_total_tb:,.1f}", "neutral")
    with cols[5]:
        card("ASM free TB", f"{asm_free_tb:,.1f}", "OK")
    with cols[6]:
        card("HugePages critical hosts", hp_critical, "CRITICAL" if hp_critical else "OK")
    with cols[7]:
        card("Total DBs", total_dbs, "neutral")
    with cols[8]:
        card("Primary DBs", primary_dbs, "neutral")
    with cols[9]:
        card("Standby DBs", standby_dbs, "neutral")
    with cols[10]:
        card("DB space warnings", db_warnings, "WARNING" if db_warnings else "OK")
    with cols[11]:
        card("DB collection failures", db_failures, "WARNING" if db_failures else "OK")


def render_action_required(health: pd.DataFrame) -> None:
    """Show health recommendations that need executive action."""

    st.markdown("### Action Required")
    action_columns = ["cluster", "host", "warning_level", "category", "recommendation"]
    action = ensure_columns(health, action_columns)[action_columns].copy()
    action = action[(action["warning_level"].isin(["CRITICAL", "WARNING"])) & action["recommendation"].notna()]
    action = action[action["recommendation"].astype(str).str.strip() != ""]
    if action.empty:
        st.success("No CRITICAL or WARNING recommendations found in health_summary.")
    else:
        st.dataframe(action.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)


def render_executive_cockpit(filters: dict[str, list[str]]) -> None:
    """Render the default executive cockpit page."""

    health_df, health_path = read_output("health_summary")
    asm_df, asm_path = read_output("asm_diskgroups")
    huge_df, huge_path = read_output("hugepages")
    os_df, os_path = read_output("os_inventory")
    db_df, _ = read_output("db_resource_details")
    db_errors_df, _ = read_output("db_resource_details_errors")
    memory_summary_df, memory_summary_path = read_output("db_memory_history_summary")
    performance_df, performance_path = read_output("db_performance")

    health = apply_global_filters(normalize_health(health_df), filters)
    asm = apply_global_filters(normalize_asm(asm_df), filters)
    hugepages = apply_global_filters(normalize_hugepages(huge_df), filters)
    filesystems = apply_global_filters(explode_filesystems(os_df), filters)
    db_resources = apply_global_filters(normalize_db_resources(db_df), filters)
    db_errors = apply_global_filters(normalize_db_resource_errors(db_errors_df), filters)
    memory_summary = apply_global_filters(normalize_db_memory_summary(memory_summary_df), filters)
    performance = apply_global_filters(normalize_db_performance(performance_df), filters)

    st.title("Executive Exadata Resource Cockpit")
    st.caption("Executive risk, capacity, and action view from local collector output only.")
    render_kpis(health, asm, hugepages, db_resources, db_errors)

    st.markdown("### Memory Risk Snapshot")
    if memory_summary_path is None or memory_summary.empty:
        st.info("No db_memory_history_summary output found. Run the DB memory history collector to populate memory risk KPIs.")
    else:
        show_source(memory_summary_path)
        critical_memory = int((memory_summary["warning_severity"] == "CRITICAL").sum())
        warning_memory = int((memory_summary["warning_severity"] == "WARNING").sum())
        info_memory = int((memory_summary["warning_severity"] == "INFO").sum())
        top_sga = memory_summary.dropna(subset=["sga_used_gb_max"]).nlargest(1, "sga_used_gb_max")
        top_pga = memory_summary.dropna(subset=["pga_allocated_gb_max"]).nlargest(1, "pga_allocated_gb_max")

        def top_memory_value(top: pd.DataFrame, metric: str) -> str:
            if top.empty:
                return "N/A"
            row = top.iloc[0]
            database = row["db_unique_name"] if pd.notna(row["db_unique_name"]) else row["db_name"]
            return f"{database} ({row[metric]:,.1f} GB)"

        memory_metrics = [
            ("Critical memory findings", critical_memory, "CRITICAL" if critical_memory else "OK"),
            ("Warning memory findings", warning_memory, "WARNING" if warning_memory else "OK"),
            ("Info memory findings", info_memory, "INFO" if info_memory else "OK"),
            ("Top SGA consumer", top_memory_value(top_sga, "sga_used_gb_max"), "neutral"),
            ("Top PGA consumer", top_memory_value(top_pga, "pga_allocated_gb_max"), "neutral"),
        ]
        for container, (label, value, state) in zip(st.columns(5), memory_metrics):
            with container:
                card(label, value, state)

    st.markdown("### Performance Risk Snapshot")
    performance_summary = build_performance_summary(performance)
    if performance_path is None or performance_summary.empty:
        st.info("No db_performance output found. Run the DB performance collector to populate performance risk KPIs.")
    else:
        show_source(performance_path)
        top_cpu = performance_summary.dropna(subset=["max_db_cpu_per_sec"]).nlargest(
            1, "max_db_cpu_per_sec"
        )
        top_iops = performance_summary.dropna(subset=["max_total_iops"]).nlargest(
            1, "max_total_iops"
        )

        def top_performance_db(top: pd.DataFrame, metric: str) -> str:
            if top.empty:
                return "N/A"
            row = top.iloc[0]
            return f"{row['db_name']} / {row['instance_name']} ({row[metric]:,.1f})"

        max_host_cpu = performance_summary["max_host_cpu_util_pct"].max()
        performance_metrics = [
            ("Max host CPU %", _metric_number(max_host_cpu), cpu_performance_severity(max_host_cpu)),
            ("Top CPU DB", top_performance_db(top_cpu, "max_db_cpu_per_sec"), "neutral"),
            ("Max IOPS", _metric_number(performance_summary["max_total_iops"].max()), "neutral"),
            ("Top IOPS DB", top_performance_db(top_iops, "max_total_iops"), "neutral"),
        ]
        for container, (label, value, state) in zip(st.columns(4), performance_metrics):
            with container:
                card(label, value, state)

    st.markdown("### Critical Issues")
    show_source(health_path)
    critical = ensure_columns(health, ["cluster", "host", "warning_level", "category", "message", "recommendation"])
    critical = critical[critical["warning_level"] == "CRITICAL"]
    if critical.empty:
        st.success("No CRITICAL issues found in health_summary.")
    else:
        st.dataframe(critical.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    render_action_required(health)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("### ASM Capacity")
        show_source(asm_path)
        if asm.empty or asm["used_pct"].dropna().empty:
            st.info("No ASM capacity percentages available.")
        else:
            asm_chart = asm.dropna(subset=["cluster", "diskgroup_name", "used_pct"]).copy()
            asm_chart["cluster_diskgroup"] = asm_chart["cluster"].astype(str) + " / " + asm_chart["diskgroup_name"].astype(str)
            fig = px.bar(
                asm_chart,
                x="cluster_diskgroup",
                y="used_pct",
                color="warning_level",
                color_discrete_map=LEVEL_COLORS,
                title="ASM diskgroup used %",
                labels={"cluster_diskgroup": "Cluster / Diskgroup", "used_pct": "Used %"},
            )
            fig.update_yaxes(range=[0, max(100, float(asm_chart["used_pct"].max()))])
            st.plotly_chart(fig, use_container_width=True)

    with chart_col2:
        st.markdown("### HugePages Risk")
        show_source(huge_path)
        if hugepages.empty or hugepages["hugepages_free_pct"].dropna().empty:
            st.info("No HugePages free percentage data available.")
        else:
            fig = px.bar(
                hugepages.dropna(subset=["host", "hugepages_free_pct"]),
                x="host",
                y="hugepages_free_pct",
                color="warning_level",
                color_discrete_map=LEVEL_COLORS,
                title="HugePages free % by host",
                labels={"hugepages_free_pct": "Free %"},
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Filesystem Critical/Warning Exposure")
    show_source(os_path)
    risky_fs = filesystems[filesystems["warning_level"].isin(["CRITICAL", "WARNING"])] if not filesystems.empty else pd.DataFrame()
    if risky_fs.empty:
        st.success("No filesystem CRITICAL or WARNING risks found.")
    else:
        counts = risky_fs.groupby(["cluster", "warning_level"], dropna=False).size().reset_index(name="filesystems")
        fig = px.bar(
            counts,
            x="cluster",
            y="filesystems",
            color="warning_level",
            color_discrete_map=LEVEL_COLORS,
            barmode="group",
            title="Filesystem risk count by cluster",
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Lower section: filtered health_summary raw table"):
        st.dataframe(health.drop(columns=["severity_rank"], errors="ignore").style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)
    with st.expander("Lower section: filtered ASM raw table"):
        st.dataframe(asm.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)
    with st.expander("Lower section: filtered HugePages raw table"):
        st.dataframe(hugepages.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)


def render_asm_page(filters: dict[str, list[str]]) -> None:
    st.title("ASM Capacity")
    df, path = read_output("asm_diskgroups")
    show_source(path)
    if df.empty:
        st.warning("No asm_diskgroups output found in output/.")
        return

    table = apply_global_filters(normalize_asm(df), filters)
    st.markdown("### Cluster-level Summary")
    summary = table.groupby("cluster", dropna=False).agg(
        diskgroups=("diskgroup_name", "nunique"),
        hosts=("host", "nunique"),
        total_tb=("total_tb", "sum"),
        free_tb=("free_tb", "sum"),
        usable_tb=("usable_tb", "sum"),
        max_used_pct=("used_pct", "max"),
    ).reset_index()
    summary["warning_level"] = summary["max_used_pct"].map(warning_from_pct)
    st.dataframe(summary.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    st.markdown("### Diskgroup Used %")
    chart = table.dropna(subset=["diskgroup_name", "used_pct"])
    if chart.empty:
        st.info("No diskgroup used_pct values available.")
    else:
        fig = px.bar(
            chart,
            x="diskgroup_name",
            y="used_pct",
            color="warning_level",
            facet_col="cluster" if chart["cluster"].nunique(dropna=True) > 1 else None,
            color_discrete_map=LEVEL_COLORS,
            hover_data=["host", "total_tb", "free_tb", "usable_tb"],
            title="ASM diskgroup used_pct",
        )
        fig.update_yaxes(range=[0, max(100, float(chart["used_pct"].max()))])
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Host-level Detail")
    st.dataframe(table.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)


def render_hugepages_page(filters: dict[str, list[str]]) -> None:
    st.title("HugePages Risk")
    df, path = read_output("hugepages")
    show_source(path)
    if df.empty:
        st.warning("No hugepages output found in output/.")
        return

    table = apply_global_filters(normalize_hugepages(df), filters)
    st.markdown("### Free % by Host")
    if table["hugepages_free_pct"].dropna().empty:
        st.info("No hugepages_free_pct values available.")
    else:
        fig = px.bar(
            table.dropna(subset=["host", "hugepages_free_pct"]),
            x="host",
            y="hugepages_free_pct",
            color="warning_level",
            color_discrete_map=LEVEL_COLORS,
            hover_data=["cluster", "hugepages_total", "hugepages_free"],
            title="HugePages free_pct by host",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### CRITICAL Hosts")
    critical = table[table["warning_level"] == "CRITICAL"]
    if critical.empty:
        st.success("No HugePages CRITICAL hosts found.")
    else:
        st.dataframe(critical.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    with st.expander("Raw HugePages detail", expanded=False):
        st.dataframe(table.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)


def render_host_inventory_page(filters: dict[str, list[str]]) -> None:
    st.title("Host Inventory")
    df, path = read_output("os_inventory")
    show_source(path)
    if df.empty:
        st.warning("No os_inventory output found in output/.")
        return

    host_df = apply_global_filters(ensure_columns(df, ["cluster", "host", "hostname", "status", "uptime", "cpu_json", "meminfo_json", "cpu", "meminfo"]), filters)
    filesystems = apply_global_filters(explode_filesystems(df), filters)

    st.markdown("### Filesystem Risks")
    risky = filesystems[filesystems["warning_level"].isin(["CRITICAL", "WARNING"])] if not filesystems.empty else pd.DataFrame()
    if risky.empty:
        st.success("No filesystem CRITICAL or WARNING risks found.")
    else:
        display_columns = ["cluster", "host", "filesystem", "mount", "used_pct", "warning_level"]
        st.dataframe(ensure_columns(risky, display_columns)[display_columns].style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    st.markdown("### CPU and Memory Summary")
    hidden_raw = ["cpu_json", "meminfo_json"]
    summary = host_df.drop(columns=hidden_raw, errors="ignore")
    st.dataframe(summary, use_container_width=True, hide_index=True)

    with st.expander("Show raw cpu_json and meminfo_json", expanded=False):
        st.dataframe(host_df, use_container_width=True, hide_index=True)

    with st.expander("All filesystem details", expanded=False):
        if filesystems.empty:
            st.info("No filesystem details were available in os_inventory.")
        else:
            st.dataframe(filesystems.drop(columns=["severity_rank"], errors="ignore").style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)


def summarize_db_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Extract compact DB inventory details from nested collector output."""

    rows: list[dict[str, Any]] = []
    for _, record in df.iterrows():
        databases = parse_json_value(record.get("databases", record.get("databases_json", [])))
        pmon = parse_json_value(record.get("pmon_processes", record.get("pmon_processes_json", [])))
        srvctl_status = parse_json_value(record.get("srvctl_status", record.get("srvctl_status_json", {})))

        db_names: list[str] = []
        if isinstance(databases, list):
            for database in databases:
                if isinstance(database, dict):
                    name = database.get("db_unique_name") or database.get("name") or database.get("database")
                    if name:
                        db_names.append(str(name))
                elif database:
                    db_names.append(str(database))
        elif isinstance(databases, dict):
            db_names = [str(key) for key in databases.keys()]

        pmon_instances: list[str] = []
        if isinstance(pmon, list):
            for process in pmon:
                if isinstance(process, dict):
                    instance = process.get("instance") or process.get("sid") or process.get("name") or process.get("cmd")
                    if instance:
                        pmon_instances.append(str(instance))
                elif process:
                    pmon_instances.append(str(process))

        rows.append(
            {
                "cluster": record.get("cluster"),
                "host": record.get("host"),
                "db_unique_names": ", ".join(sorted(set(db_names))),
                "gi_version": record.get("gi_version"),
                "pmon_instances": ", ".join(sorted(set(pmon_instances))),
                "srvctl_status": json.dumps(srvctl_status, sort_keys=True) if isinstance(srvctl_status, (dict, list)) else srvctl_status,
                "status": record.get("status"),
            }
        )
    return pd.DataFrame(rows)


def render_db_inventory_page(filters: dict[str, list[str]]) -> None:
    st.title("DB Inventory")

    raw_df, path = read_output("db_resource_details")
    errors_df, errors_path = read_output("db_resource_details_errors")
    show_source(path)
    if raw_df.empty:
        st.warning("No db_resource_details output found in output/.")
        return

    table = apply_global_filters(normalize_db_resources(raw_df), filters)
    deduped = dedupe_db_resources(table)

    st.markdown("## DB Resource Overview")
    primary_count = int(deduped["db_role"].astype(str).str.upper().str.contains("PRIMARY", na=False).sum())
    standby_count = int(deduped["db_role"].astype(str).str.upper().str.contains("STANDBY", na=False).sum())
    rac_count = int(deduped["rac_enabled"].astype(str).str.upper().isin(["TRUE", "YES", "Y"]).sum())
    over_85 = int((deduped["db_used_pct"] >= 85).sum())
    over_95 = int((deduped["db_used_pct"] >= 95).sum())
    total_size_tb = deduped["db_size_gb"].sum(skipna=True) / 1024
    total_used_tb = deduped["used_db_size_gb"].sum(skipna=True) / 1024

    kpis = st.columns(8)
    metrics = [
        ("Total DBs collected", len(deduped)),
        ("Primary DB count", primary_count),
        ("Standby DB count", standby_count),
        ("RAC DB count", rac_count),
        ("Total DB size TB", f"{total_size_tb:,.2f}"),
        ("Total used DB size TB", f"{total_used_tb:,.2f}"),
        ("DBs over 85% used", over_85),
        ("DBs over 95% used", over_95),
    ]
    for col, (label, value) in zip(kpis, metrics, strict=False):
        with col:
            st.metric(label, value)

    st.markdown("### DB Resource Filters")
    filter_cols = st.columns(6)
    local_filters: dict[str, Any] = {}
    for col, field, label in zip(filter_cols[:5], ["cluster", "db_role", "open_mode", "version", "rac_enabled"], ["Cluster", "DB role", "Open mode", "Version", "RAC enabled"], strict=False):
        values = sorted({str(value) for value in table[field].dropna() if str(value).strip()}) if field in table.columns else []
        with col:
            local_filters[field] = st.multiselect(label, values, default=[])
    with filter_cols[5]:
        threshold = st.number_input("DB used % threshold", min_value=0.0, max_value=100.0, value=0.0, step=5.0)

    filtered = table.copy()
    for field, selected in local_filters.items():
        if selected:
            filtered = filtered[filtered[field].astype(str).isin(selected)]
    if threshold > 0:
        filtered = filtered[filtered["db_used_pct"] >= threshold]
    filtered_deduped = dedupe_db_resources(filtered)

    st.markdown("## DB Resource Table")
    display_columns = [
        "cluster",
        "db_unique_name",
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
        "oracle_home",
        "oracle_sid",
        "host_name",
    ]
    st.dataframe(ensure_columns(filtered, display_columns)[display_columns], use_container_width=True, hide_index=True)

    st.markdown("## DB Resource Charts")
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        top_size = filtered_deduped.nlargest(15, "db_size_gb") if not filtered_deduped.empty else pd.DataFrame()
        if top_size.empty:
            st.info("No DB_SIZE_GB values available.")
        else:
            st.plotly_chart(px.bar(top_size, x="db_unique_name", y="db_size_gb", color="cluster", title="Top 15 DBs by DB_SIZE_GB"), use_container_width=True)
    with chart_col2:
        top_used = filtered_deduped.nlargest(15, "used_db_size_gb") if not filtered_deduped.empty else pd.DataFrame()
        if top_used.empty:
            st.info("No USED_DB_SIZE_GB values available.")
        else:
            st.plotly_chart(px.bar(top_used, x="db_unique_name", y="used_db_size_gb", color="cluster", title="Top 15 DBs by USED_DB_SIZE_GB"), use_container_width=True)

    chart_col3, chart_col4 = st.columns(2)
    with chart_col3:
        if filtered_deduped.empty:
            st.info("No DB role values available.")
        else:
            role_counts = filtered_deduped.groupby("db_role", dropna=False).size().reset_index(name="db_count")
            st.plotly_chart(px.bar(role_counts, x="db_role", y="db_count", title="DB count by role"), use_container_width=True)
    with chart_col4:
        if filtered_deduped.empty:
            st.info("No DB version values available.")
        else:
            version_counts = filtered_deduped.groupby("version", dropna=False).size().reset_index(name="db_count")
            st.plotly_chart(px.bar(version_counts, x="version", y="db_count", title="DB count by version"), use_container_width=True)

    over_80 = filtered_deduped[filtered_deduped["db_used_pct"] > 80]
    if over_80.empty:
        st.success("No DBs over 80% used.")
    else:
        st.plotly_chart(px.bar(over_80.sort_values("db_used_pct", ascending=False), x="db_unique_name", y="db_used_pct", color="cluster", title="DB used percentage for DBs over 80%"), use_container_width=True)

    st.markdown("## DB Collection Errors")
    show_source(errors_path)
    errors = apply_global_filters(normalize_db_resource_errors(errors_df), filters)
    failed = errors[errors["collection_status"].astype(str).str.lower() == "failed"] if not errors.empty else pd.DataFrame()
    skipped = errors[errors["collection_status"].astype(str).str.lower() == "skipped"] if not errors.empty else pd.DataFrame()
    if failed.empty:
        st.success("No failed DB resource collection rows found.")
    else:
        st.dataframe(failed, use_container_width=True, hide_index=True)
    with st.expander("Skipped DBs with no local running instance", expanded=False):
        if skipped.empty:
            st.info("No skipped DB rows found.")
        else:
            st.dataframe(skipped, use_container_width=True, hide_index=True)


def apply_version_inventory_health(
    version_inventory: pd.DataFrame, health_summary: pd.DataFrame
) -> pd.DataFrame:
    """Apply collector-owned imageinfo health decisions to version inventory rows."""

    table = version_inventory.copy()
    health = ensure_columns(
        health_summary, ["cluster", "host", "category", "metric", "warning_level"]
    )
    imageinfo_health = health[
        (health["category"] == "VERSION_INVENTORY")
        & (health["metric"] == "imageinfo_available")
    ][["cluster", "host", "warning_level"]].rename(
        columns={"warning_level": "imageinfo_warning_level"}
    )
    table = table.merge(imageinfo_health, on=["cluster", "host"], how="left")
    table["missing_imageinfo"] = table["imageinfo_warning_level"].notna()
    table["warning_level"] = table["imageinfo_warning_level"].fillna(
        table["warning_level"]
    )
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    return table.drop(columns=["imageinfo_warning_level"])


def render_version_inventory_page(filters: dict[str, list[str]]) -> None:
    st.title("Version Inventory")
    df, path = read_output("version_inventory")
    show_source(path)
    columns = [
        "cluster",
        "host",
        "image_version",
        "exadata_software_version",
        "gi_release_patch_string",
        "gi_release_version",
        "warning_level",
    ]
    if df.empty:
        st.warning("No version_inventory output found in output/.")
        return

    table = ensure_columns(df, columns)[columns].copy()
    health_df, _ = read_output("health_summary")
    table = apply_version_inventory_health(table, health_df)
    table = apply_global_filters(table, filters)

    st.markdown("### GI Patch Compliance by Cluster")
    compliance = table.groupby("cluster", dropna=False).agg(
        hosts=("host", "nunique"),
        gi_patch_variants=("gi_release_patch_string", lambda values: values.dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()),
        missing_imageinfo_hosts=("missing_imageinfo", "sum"),
        gi_release_patch_string=("gi_release_patch_string", lambda values: "; ".join(sorted({str(value) for value in values.dropna() if str(value).strip()}))),
    ).reset_index()
    compliance["compliance"] = compliance.apply(
        lambda row: "WARNING" if row["missing_imageinfo_hosts"] or row["gi_patch_variants"] > 1 else "OK",
        axis=1,
    )
    compliance = compliance.rename(columns={"compliance": "warning_level"})
    st.dataframe(compliance.style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    st.markdown("### Missing imageinfo Warnings")
    missing = table[table["missing_imageinfo"]]
    if missing.empty:
        st.success("No missing imageinfo records found.")
    else:
        st.dataframe(missing[columns + ["missing_imageinfo"]].style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)

    with st.expander("Raw version inventory detail", expanded=False):
        st.dataframe(table[columns + ["missing_imageinfo"]].style.apply(apply_warning_style, axis=None), use_container_width=True, hide_index=True)



def _render_date_filter(table: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    if table.empty or table["end_time"].dropna().empty:
        return table
    min_date = table["end_time"].min().date()
    max_date = table["end_time"].max().date()
    start_date, end_date = st.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date, key=f"{key_prefix}_date_range")
    return table[(table["end_time"].dt.date >= start_date) & (table["end_time"].dt.date <= end_date)]


def render_performance_filters(table: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Render cluster, DB, instance, host, and date filters for performance data."""

    filtered = table.copy()
    filter_specs = [
        ("cluster", "Cluster"),
        ("db_name", "DB name"),
        ("instance_name", "Instance"),
        ("host_name", "Host"),
    ]
    containers = st.columns(len(filter_specs))
    for (column, label), container in zip(filter_specs, containers):
        values = sorted(
            {str(value) for value in filtered[column].dropna() if str(value).strip()}
        ) if column in filtered.columns else []
        selected = container.multiselect(
            label, values, default=[], key=f"{key_prefix}_{column}"
        )
        if selected:
            filtered = filtered[filtered[column].astype(str).isin(selected)]
    return _render_date_filter(filtered, key_prefix)


def _render_db_perf_filters(
    table: pd.DataFrame,
    key_prefix: str,
    include_db_unique_name: bool = False,
) -> pd.DataFrame:
    """Render local DB history filters and return matching rows."""

    if not include_db_unique_name:
        return render_performance_filters(table, key_prefix)

    filtered = render_performance_filters(table, key_prefix)
    values = sorted(
        {str(value) for value in filtered["db_unique_name"].dropna() if str(value).strip()}
    ) if "db_unique_name" in filtered.columns else []
    selected = st.multiselect(
        "DB unique name", values, default=[], key=f"{key_prefix}_db_unique_name"
    )
    if selected:
        filtered = filtered[filtered["db_unique_name"].astype(str).isin(selected)]
    return filtered


def _performance_instance_label(table: pd.DataFrame) -> pd.Series:
    """Return a readable database/instance/host label for performance charts."""

    return (
        table["db_name"].fillna("Unknown DB").astype(str)
        + " / " + table["instance_name"].fillna("Unknown instance").astype(str)
        + " / " + table["host_name"].fillna("Unknown host").astype(str)
    )


def _render_performance_metrics(metrics: list[tuple[str, Any]]) -> None:
    """Render compact KPI metrics across one or more four-column rows."""

    for offset in range(0, len(metrics), 4):
        row = metrics[offset:offset + 4]
        for container, (label, value) in zip(st.columns(len(row)), row):
            container.metric(label, value)


def _metric_number(value: Any, decimals: int = 1) -> str:
    """Format an optional numeric KPI without exposing NaN values."""

    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "N/A" if pd.isna(number) else f"{float(number):,.{decimals}f}"


def render_db_performance_page(filters: dict[str, list[str]]) -> None:
    st.title("DB Performance")
    st.caption("Uses DBA_HIST_SYSMETRIC_SUMMARY AWR data; ensure Oracle Diagnostics Pack licensing before enabling collection.")
    df, path = read_output("db_performance")
    show_source(path)
    table = apply_global_filters(normalize_db_performance(df), filters)
    if table.empty:
        st.warning("No db_performance output found in output/.")
        return
    table = render_performance_filters(table, "db_perf")
    if table.empty:
        st.info("No DB performance rows match the selected filters.")
        return
    chart1, chart2 = st.columns(2)
    with chart1:
        st.plotly_chart(px.line(table, x="end_time", y="total_iops_avg", color="db_name", line_dash="instance_name", title="Total IOPS over time"), use_container_width=True)
    with chart2:
        st.plotly_chart(px.line(table, x="end_time", y="total_mbps_avg", color="db_name", line_dash="instance_name", title="Total MBPS over time"), use_container_width=True)
    chart3, chart4 = st.columns(2)
    with chart3:
        st.plotly_chart(px.line(table, x="end_time", y="cpu_usage_per_sec_avg", color="db_name", line_dash="instance_name", title="CPU Usage Per Sec over time"), use_container_width=True)
    with chart4:
        st.plotly_chart(px.line(table, x="end_time", y="host_cpu_util_pct_avg", color="db_name", line_dash="instance_name", title="Host CPU Utilization % over time"), use_container_width=True)
    top = table.groupby(["cluster", "db_name"], dropna=False).agg(avg_iops=("total_iops_avg", "mean"), max_iops=("total_iops_max", "max")).reset_index()
    chart5, chart6 = st.columns(2)
    with chart5:
        st.plotly_chart(px.bar(top.nlargest(15, "avg_iops"), x="db_name", y="avg_iops", color="cluster", title="Top DBs by avg IOPS"), use_container_width=True)
    with chart6:
        st.plotly_chart(px.bar(top.nlargest(15, "max_iops"), x="db_name", y="max_iops", color="cluster", title="Top DBs by max IOPS"), use_container_width=True)
    st.dataframe(table, use_container_width=True, hide_index=True)


def render_cpu_analytics_page(filters: dict[str, list[str]]) -> None:
    """Render focused database and host CPU analytics from local AWR output."""

    st.title("CPU Analytics")
    st.caption("Uses local db_performance output only; Oracle Diagnostics Pack licensing may apply to the source AWR data.")
    df, path = read_output("db_performance")
    if path is None or df.empty:
        st.warning("No db_performance output found. Run the DB performance collector first.")
        return
    show_source(path)
    table = apply_global_filters(normalize_db_performance(df), filters)
    table = render_performance_filters(table, "cpu_analytics")
    if table.empty:
        st.info("No CPU performance rows match the selected filters.")
        return

    summary = build_performance_summary(table)
    if summary.empty:
        st.info("No CPU performance rows with a valid end_time match the selected filters.")
        return
    summary["warning_level"] = summary["max_host_cpu_util_pct"].map(
        cpu_performance_severity
    )
    _render_performance_metrics([
        ("DB instances analyzed", len(summary)),
        ("Avg DB CPU per sec", _metric_number(summary["avg_db_cpu_per_sec"].mean())),
        ("Max DB CPU per sec", _metric_number(summary["max_db_cpu_per_sec"].max())),
        ("Avg host CPU %", _metric_number(summary["avg_host_cpu_util_pct"].mean())),
        ("Max host CPU %", _metric_number(summary["max_host_cpu_util_pct"].max())),
        ("Hosts/instances over 80% host CPU", int((summary["max_host_cpu_util_pct"] >= 80).sum())),
        ("Hosts/instances over 90% host CPU", int((summary["max_host_cpu_util_pct"] >= 90).sum())),
    ])

    st.markdown("### CPU trends")
    chart1, chart2 = st.columns(2)
    with chart1:
        st.plotly_chart(
            px.line(table, x="end_time", y="cpu_usage_per_sec_avg", color="db_name",
                    line_dash="instance_name", title="DB CPU usage per sec over time"),
            use_container_width=True,
        )
    with chart2:
        st.plotly_chart(
            px.line(table, x="end_time", y="host_cpu_util_pct_avg", color="host_name",
                    line_dash="instance_name", title="Host CPU utilization % over time"),
            use_container_width=True,
        )

    st.markdown("### Top CPU consumers")
    chart3, chart4 = st.columns(2)
    chart_summary = summary.assign(db_instance=_performance_instance_label(summary))
    with chart3:
        st.plotly_chart(
            px.bar(chart_summary.nlargest(20, "max_db_cpu_per_sec"), x="db_instance",
                   y="max_db_cpu_per_sec", color="cluster",
                   title="Top 20 by max DB CPU per sec"),
            use_container_width=True,
        )
    with chart4:
        st.plotly_chart(
            px.bar(chart_summary.nlargest(20, "max_host_cpu_util_pct"), x="db_instance",
                   y="max_host_cpu_util_pct", color="cluster",
                   title="Top 20 by max host CPU utilization %"),
            use_container_width=True,
        )

    st.markdown("### CPU risk table")
    cpu_values = summary["max_db_cpu_per_sec"].dropna()
    relative_cpu_threshold = cpu_values.quantile(0.90) if not cpu_values.empty else pd.NA
    if pd.notna(relative_cpu_threshold):
        st.caption(
            f"Relative DB CPU risk cutoff: 90th percentile "
            f"({float(relative_cpu_threshold):,.1f} CPU per sec)."
        )
    risk = summary[
        (summary["max_host_cpu_util_pct"] >= 80)
        | (
            pd.notna(relative_cpu_threshold)
            & (summary["max_db_cpu_per_sec"] >= relative_cpu_threshold)
        )
    ].copy()
    risk_columns = [
        "cluster", "host_name", "db_name", "instance_name", "snapshot_count",
        "begin_time_min", "end_time_max", "avg_db_cpu_per_sec",
        "max_db_cpu_per_sec", "avg_host_cpu_util_pct",
        "max_host_cpu_util_pct", "warning_level",
    ]
    if risk.empty:
        st.success("No host CPU threshold or relative DB CPU risks found.")
    else:
        risk = risk.sort_values(
            ["max_host_cpu_util_pct", "max_db_cpu_per_sec"], ascending=False
        )
        st.dataframe(
            risk[risk_columns].style.apply(apply_warning_style, axis=None),
            use_container_width=True, hide_index=True,
        )


def render_iops_analytics_page(filters: dict[str, list[str]]) -> None:
    """Render focused IOPS and throughput analytics from local AWR output."""

    st.title("IOPS Analytics")
    st.caption("Uses local db_performance output only; Oracle Diagnostics Pack licensing may apply to the source AWR data.")
    df, path = read_output("db_performance")
    if path is None or df.empty:
        st.warning("No db_performance output found. Run the DB performance collector first.")
        return
    show_source(path)
    table = apply_global_filters(normalize_db_performance(df), filters)
    table = render_performance_filters(table, "iops_analytics")
    if table.empty:
        st.info("No IOPS performance rows match the selected filters.")
        return

    st.markdown("### Risk thresholds")
    threshold_columns = st.columns(4)
    warning_iops = threshold_columns[0].number_input(
        "IOPS warning threshold", min_value=0.0, value=5000.0, step=500.0
    )
    critical_iops = threshold_columns[1].number_input(
        "IOPS critical threshold", min_value=0.0, value=10000.0, step=500.0
    )
    warning_mbps = threshold_columns[2].number_input(
        "MBPS warning threshold", min_value=0.0, value=500.0, step=50.0
    )
    critical_mbps = threshold_columns[3].number_input(
        "MBPS critical threshold", min_value=0.0, value=1000.0, step=50.0
    )
    summary = build_performance_summary(table)
    if summary.empty:
        st.info("No IOPS performance rows with a valid end_time match the selected filters.")
        return
    summary["warning_level"] = summary.apply(
        lambda row: iops_performance_severity(
            row["max_total_iops"], row["max_total_mbps"], warning_iops,
            critical_iops, warning_mbps, critical_mbps
        ),
        axis=1,
    )
    _render_performance_metrics([
        ("DB instances analyzed", len(summary)),
        ("Avg IOPS", _metric_number(summary["avg_total_iops"].mean())),
        ("Max IOPS", _metric_number(summary["max_total_iops"].max())),
        ("Avg MBPS", _metric_number(summary["avg_total_mbps"].mean())),
        ("Max MBPS", _metric_number(summary["max_total_mbps"].max())),
        ("DBs over high IOPS threshold", int((summary["max_total_iops"] >= warning_iops).sum())),
        ("DBs over high MBPS threshold", int((summary["max_total_mbps"] >= warning_mbps).sum())),
    ])

    st.markdown("### IOPS trends")
    chart1, chart2 = st.columns(2)
    with chart1:
        st.plotly_chart(px.line(table, x="end_time", y="total_iops_avg", color="db_name",
                                line_dash="instance_name", title="Total IOPS avg over time"),
                        use_container_width=True)
    with chart2:
        st.plotly_chart(px.line(table, x="end_time", y="total_iops_max", color="db_name",
                                line_dash="instance_name", title="Total IOPS max over time"),
                        use_container_width=True)

    st.markdown("### Throughput trends")
    chart3, chart4 = st.columns(2)
    with chart3:
        st.plotly_chart(px.line(table, x="end_time", y="total_mbps_avg", color="db_name",
                                line_dash="instance_name", title="Total MBPS avg over time"),
                        use_container_width=True)
    with chart4:
        st.plotly_chart(px.line(table, x="end_time", y="total_mbps_max", color="db_name",
                                line_dash="instance_name", title="Total MBPS max over time"),
                        use_container_width=True)

    st.markdown("### Top IO consumers")
    chart_summary = summary.assign(db_instance=_performance_instance_label(summary))
    chart5, chart6 = st.columns(2)
    with chart5:
        st.plotly_chart(px.bar(chart_summary.nlargest(20, "max_total_iops"),
                               x="db_instance", y="max_total_iops", color="cluster",
                               title="Top 20 DB instances by max total IOPS"),
                        use_container_width=True)
    with chart6:
        st.plotly_chart(px.bar(chart_summary.nlargest(20, "max_total_mbps"),
                               x="db_instance", y="max_total_mbps", color="cluster",
                               title="Top 20 DB instances by max total MBPS"),
                        use_container_width=True)

    st.markdown("### IOPS risk table")
    risk = summary[
        (summary["max_total_iops"] >= warning_iops)
        | (summary["max_total_mbps"] >= warning_mbps)
    ].copy()
    risk_columns = [
        "cluster", "host_name", "db_name", "instance_name", "snapshot_count",
        "begin_time_min", "end_time_max", "avg_total_iops", "max_total_iops",
        "avg_total_mbps", "max_total_mbps", "warning_level",
    ]
    if risk.empty:
        st.success("No DB instances exceed the selected IOPS or MBPS warning thresholds.")
    else:
        risk = risk.sort_values(["max_total_iops", "max_total_mbps"], ascending=False)
        st.dataframe(
            risk[risk_columns].style.apply(apply_warning_style, axis=None),
            use_container_width=True, hide_index=True,
        )

def render_db_memory_history_page(filters: dict[str, list[str]]) -> None:
    """Render detailed SGA/PGA history for selected DB instances."""

    st.title("DB Memory History")
    st.caption("Uses DBA_HIST_* AWR memory views; ensure Oracle Diagnostics Pack licensing before enabling collection.")
    df, path = read_output("db_memory_history")
    show_source(path)
    table = apply_global_filters(normalize_db_memory_history(df), filters)
    if table.empty:
        st.warning("No db_memory_history output found in output/.")
        return
    table = _render_db_perf_filters(table, "db_mem", include_db_unique_name=True)
    if table.empty:
        st.info("No memory history rows match the selected cluster, DB, instance, DB unique name, and date filters.")
        return

    chart1, chart2, chart3 = st.columns(3)
    with chart1:
        st.plotly_chart(
            px.line(table, x="end_time", y="sga_used_gb", color="db_name", line_dash="instance_name", title="SGA_USED_GB over time"),
            use_container_width=True,
        )
    with chart2:
        st.plotly_chart(
            px.line(table, x="end_time", y="pga_allocated_gb", color="db_name", line_dash="instance_name", title="PGA_ALLOCATED_GB over time"),
            use_container_width=True,
        )
    with chart3:
        st.plotly_chart(
            px.line(table, x="end_time", y="pga_used_gb", color="db_name", line_dash="instance_name", title="PGA_USED_GB over time"),
            use_container_width=True,
        )

    component_candidates = [
        "sga_buffer_cache_gb", "sga_shared_pool_gb", "sga_large_pool_gb", "sga_other_gb",
        "sga_fixed_gb", "sga_redo_gb",
    ]
    component_columns = [column for column in component_candidates if table[column].notna().any()]
    if not component_columns:
        st.info("SGA component values are not present in this db_memory_history output.")
    else:
        component_long = table.melt(
            id_vars=["end_time", "cluster", "db_name", "instance_name"],
            value_vars=component_columns,
            var_name="component",
            value_name="gb",
        ).dropna(subset=["gb"])
        st.plotly_chart(
            px.line(
                component_long,
                x="end_time",
                y="gb",
                color="component",
                line_dash="instance_name",
                title="SGA Components over time",
            ),
            use_container_width=True,
        )

    c1, c2 = st.columns(2)
    with c1:
        sga_long = table.melt(
            id_vars=["end_time", "db_name", "instance_name"],
            value_vars=["sga_target_gb", "sga_used_gb"],
            var_name="metric",
            value_name="gb",
        ).dropna(subset=["gb"])
        st.plotly_chart(
            px.line(sga_long, x="end_time", y="gb", color="metric", line_dash="instance_name", title="SGA_TARGET_GB vs SGA_USED_GB"),
            use_container_width=True,
        )
    with c2:
        pga_limit_long = table.melt(
            id_vars=["end_time", "db_name", "instance_name"],
            value_vars=["pga_aggregate_limit_gb", "pga_allocated_gb"],
            var_name="metric",
            value_name="gb",
        ).dropna(subset=["gb"])
        st.plotly_chart(
            px.line(pga_limit_long, x="end_time", y="gb", color="metric", line_dash="instance_name", title="PGA_AGGREGATE_LIMIT_GB vs PGA_ALLOCATED_GB"),
            use_container_width=True,
        )

    pga_long = table.melt(
        id_vars=["end_time", "db_name", "instance_name"],
        value_vars=[
            "pga_aggregate_target_gb", "pga_aggregate_limit_gb",
            "pga_allocated_gb", "pga_used_gb",
        ],
        var_name="metric",
        value_name="gb",
    ).dropna(subset=["gb"])
    st.plotly_chart(
        px.line(
            pga_long,
            x="end_time",
            y="gb",
            color="metric",
            line_dash="instance_name",
            title="PGA target, limit, allocated, and used over time",
        ),
        use_container_width=True,
    )

    st.markdown("### Latest snapshot by instance")
    snapshot_columns = [
        "cluster", "db_unique_name", "db_name", "instance_name", "host_name", "end_time",
        "sga_used_gb", "sga_max_size_gb", "sga_buffer_cache_gb", "sga_shared_pool_gb",
        "sga_other_gb", "pga_allocated_gb", "pga_used_gb", "pga_aggregate_target_gb",
    ]
    latest = (
        table.sort_values("end_time", na_position="first")
        .groupby(["cluster", "db_name", "instance_name"], dropna=False, as_index=False)
        .tail(1)
        .sort_values(["cluster", "db_name", "instance_name"], na_position="last")
    )
    st.dataframe(latest[snapshot_columns], use_container_width=True, hide_index=True)

    with st.expander("All normalized memory history rows"):
        st.dataframe(table, use_container_width=True, hide_index=True)


def _memory_consumer_label(table: pd.DataFrame) -> pd.Series:
    db = table.get("db_unique_name", table.get("db_name", pd.Series("Unknown", index=table.index))).fillna(table.get("db_name", "Unknown")).astype(str)
    instance = table.get("instance_name", pd.Series("Unknown", index=table.index)).fillna("Unknown").astype(str)
    return db + " / " + instance


def render_memory_analytics_page(filters: dict[str, list[str]]) -> None:
    """Render memory capacity, warning, and rightsizing analytics from local files."""

    st.title("Memory Analytics")
    st.caption(
        "SGA/PGA historical summary and capacity recommendations from local output files."
    )

    summary_df, summary_path = read_output("db_memory_history_summary")
    top_df, top_path = read_output("memory_capacity_top_consumers")
    warnings_df, warnings_path = read_output("memory_warning_report")
    rightsizing_df, rightsizing_path = read_output("memory_rightsizing_candidates")
    cluster_rollup_df, cluster_rollup_path = read_output("memory_cluster_rollup")

    summary = apply_global_filters(normalize_db_memory_summary(summary_df), filters)
    if summary_path is None or summary.empty:
        st.warning(
            "No db_memory_history_summary output found. Run python main.py --collector "
            "db-memory-history --days 7 first."
        )
        return
    show_source(summary_path)

    critical = int((summary["warning_severity"] == "CRITICAL").sum())
    warning = int((summary["warning_severity"] == "WARNING").sum())
    info = int((summary["warning_severity"] == "INFO").sum())
    metrics = [
        ("DB instances analyzed", len(summary), "neutral"),
        ("Critical memory findings", critical, "CRITICAL" if critical else "OK"),
        ("Warning memory findings", warning, "WARNING" if warning else "OK"),
        ("Info memory findings", info, "INFO" if info else "OK"),
        ("Total SGA max GB", f"{summary['sga_max_size_gb_max'].sum(skipna=True):,.1f}", "neutral"),
        ("Total SGA used max GB", f"{summary['sga_used_gb_max'].sum(skipna=True):,.1f}", "neutral"),
        ("Total PGA target GB", f"{summary['pga_aggregate_target_gb_max'].sum(skipna=True):,.1f}", "neutral"),
        ("Total PGA allocated max GB", f"{summary['pga_allocated_gb_max'].sum(skipna=True):,.1f}", "neutral"),
    ]
    for container, (label, value, state) in zip(st.columns(4), metrics[:4]):
        with container:
            card(label, value, state)
    for container, (label, value, state) in zip(st.columns(4), metrics[4:]):
        with container:
            card(label, value, state)

    st.markdown("### Cluster rollup")
    rollup = apply_global_filters(
        normalize_memory_cluster_rollup(cluster_rollup_df), filters
    )
    if rollup.empty:
        rollup = build_memory_cluster_rollup(summary)
    elif cluster_rollup_path is not None:
        show_source(cluster_rollup_path)
    rollup_columns = [
        "cluster", "database_count", "instance_count", "total_sga_max_size_gb",
        "total_sga_used_gb_max", "total_pga_target_gb",
        "total_pga_allocated_gb_max", "critical_count", "warning_count",
        "info_count",
    ]
    rollup = ensure_columns(rollup, rollup_columns)
    for column in rollup_columns[1:]:
        rollup[column] = pd.to_numeric(rollup[column], errors="coerce")
    st.dataframe(rollup[rollup_columns], use_container_width=True, hide_index=True)
    rc1, rc2 = st.columns(2)
    with rc1:
        st.plotly_chart(
            px.bar(rollup, x="cluster", y="total_sga_used_gb_max",
                   title="Total SGA used max by cluster"),
            use_container_width=True,
        )
    with rc2:
        st.plotly_chart(
            px.bar(rollup, x="cluster", y="total_pga_allocated_gb_max",
                   title="Total PGA allocated max by cluster"),
            use_container_width=True,
        )

    st.markdown("### Top memory consumers")
    consumers = apply_global_filters(
        normalize_memory_capacity_top_consumers(top_df), filters
    )
    if consumers.empty:
        consumers = summary.copy()
    elif top_path is not None:
        show_source(top_path)
    consumers = ensure_columns(
        consumers,
        ["db_unique_name", "db_name", "instance_name", "cluster",
         "sga_used_gb_max", "pga_allocated_gb_max"],
    )
    for column in ["sga_used_gb_max", "pga_allocated_gb_max"]:
        consumers[column] = pd.to_numeric(consumers[column], errors="coerce")
    consumers["db_instance"] = _memory_consumer_label(consumers)
    tc1, tc2 = st.columns(2)
    with tc1:
        top_sga = consumers.dropna(subset=["sga_used_gb_max"]).nlargest(20, "sga_used_gb_max")
        if top_sga.empty:
            st.info("No SGA consumer values are available.")
        else:
            st.plotly_chart(
                px.bar(top_sga, x="db_instance", y="sga_used_gb_max",
                       color="cluster", title="Top 20 SGA consumers by sga_used_gb_max"),
                use_container_width=True,
            )
    with tc2:
        top_pga = consumers.dropna(subset=["pga_allocated_gb_max"]).nlargest(20, "pga_allocated_gb_max")
        if top_pga.empty:
            st.info("No PGA consumer values are available.")
        else:
            st.plotly_chart(
                px.bar(top_pga, x="db_instance", y="pga_allocated_gb_max",
                       color="cluster", title="Top 20 PGA consumers by pga_allocated_gb_max"),
                use_container_width=True,
            )

    st.markdown("### Warning report")
    warnings = apply_global_filters(normalize_memory_warning_report(warnings_df), filters)
    if warnings.empty:
        warnings = summary[summary["warning_severity"] != "OK"].copy()
    elif warnings_path is not None:
        show_source(warnings_path)
    warning_columns = [
        "cluster", "db_unique_name", "db_name", "instance_name", "host_name",
        "warning_severity", "warnings", "info_warnings", "warning_warnings",
        "critical_warnings", "sga_growth_headroom_gb",
        "pga_used_pct_of_target_max", "pga_allocated_gb_max",
        "pga_aggregate_target_gb_max",
    ]
    warnings = ensure_columns(warnings, warning_columns + ["warning_level"])
    if warnings.empty:
        st.success("No memory warnings found.")
    else:
        warnings["warning_level"] = warnings["warning_severity"].map(
            normalize_warning_level
        )
        styled = warnings[warning_columns + ["warning_level"]].style.apply(
            apply_warning_style, axis=None
        )
        st.dataframe(
            styled, use_container_width=True, hide_index=True,
            column_order=warning_columns
        )

    st.markdown("### Rightsizing candidates")
    rightsizing = apply_global_filters(
        normalize_memory_rightsizing_candidates(rightsizing_df), filters
    )
    if rightsizing.empty:
        st.info("Run python main.py --analyze memory to generate rightsizing candidates.")
        return
    show_source(rightsizing_path)
    rightsizing_columns = [
        "cluster", "db_unique_name", "db_name", "instance_name", "host_name",
        "recommendation_type", "current_value", "observed_peak",
        "suggested_review_action", "confidence", "warning_severity",
    ]
    rightsizing = ensure_columns(rightsizing, rightsizing_columns)
    st.dataframe(
        rightsizing[rightsizing_columns], use_container_width=True, hide_index=True
    )
    recommendation_counts = (
        rightsizing["recommendation_type"].dropna().astype(str).value_counts()
        .rename_axis("recommendation_type").reset_index(name="candidates")
    )
    if not recommendation_counts.empty:
        st.plotly_chart(
            px.bar(
                recommendation_counts, x="recommendation_type", y="candidates",
                title="Rightsizing candidates by recommendation type",
            ),
            use_container_width=True,
        )


def render_raw_data_page() -> None:
    st.title("Raw Data Explorer")
    files = sorted(path for path in OUTPUT_DIR.glob("*") if path.is_file() and path.suffix.lower() in {".json", ".csv"})
    if not files:
        st.warning("No JSON or CSV files found in output/.")
        return

    selected = st.selectbox("Choose an output file", files, format_func=lambda path: path.name)
    st.caption(f"Source: {selected}")

    if selected.suffix.lower() == ".csv":
        st.dataframe(read_file(selected), use_container_width=True)
        return

    payload = read_raw_json(selected)
    if isinstance(payload, list):
        st.dataframe(pd.DataFrame(payload), use_container_width=True)
    elif isinstance(payload, dict):
        st.dataframe(pd.json_normalize(payload), use_container_width=True)
    else:
        st.write(payload)

    with st.expander("Raw JSON"):
        st.json(payload)


def main() -> None:
    page, filters = build_global_filters()

    if page == "Executive Cockpit":
        render_executive_cockpit(filters)
    elif page == "ASM Capacity":
        render_asm_page(filters)
    elif page == "HugePages":
        render_hugepages_page(filters)
    elif page == "Host Inventory":
        render_host_inventory_page(filters)
    elif page == "Version Inventory":
        render_version_inventory_page(filters)
    elif page == "DB Inventory":
        render_db_inventory_page(filters)
    elif page == "DB Performance":
        render_db_performance_page(filters)
    elif page == "CPU Analytics":
        render_cpu_analytics_page(filters)
    elif page == "IOPS Analytics":
        render_iops_analytics_page(filters)
    elif page == "DB Memory History":
        render_db_memory_history_page(filters)
    elif page == "Memory Analytics":
        render_memory_analytics_page(filters)
    elif page == "Raw Data Explorer":
        render_raw_data_page()


if __name__ == "__main__":
    main()
