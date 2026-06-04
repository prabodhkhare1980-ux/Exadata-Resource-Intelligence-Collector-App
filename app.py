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
HEALTH_LEVELS = ["CRITICAL", "WARNING", "OK"]
LEVEL_COLORS = {
    "CRITICAL": "#d92d20",
    "WARNING": "#f59e0b",
    "OK": "#16a34a",
}
LEVEL_BACKGROUNDS = {
    "CRITICAL": "#fff1f0",
    "WARNING": "#fffbeb",
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
    "DB Memory History",
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


def normalize_warning_level(value: Any) -> str:
    """Normalize collector health levels for metrics, filters, and styling."""

    level = str(value).upper().strip() if pd.notna(value) else "OK"
    return level if level in HEALTH_LEVELS else "OK"


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


def apply_warning_style(df: pd.DataFrame) -> pd.DataFrame:
    """Return a dataframe style map for warning levels."""

    if "warning_level" not in df.columns:
        return pd.DataFrame("", index=df.index, columns=df.columns)

    styles = []
    for _, row in df.iterrows():
        level = normalize_warning_level(row.get("warning_level"))
        background = LEVEL_BACKGROUNDS.get(level, "")
        border = LEVEL_COLORS.get(level, "")
        styles.append(
            [
                f"background-color: {background}; border-left: 4px solid {border}" if background and column == df.columns[0] else f"background-color: {background}" if background else ""
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
    for column, selected in filters.items():
        if selected and column in filtered.columns:
            filtered = filtered[filtered[column].astype(str).isin(selected)]
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
        "INSTANCE_NAME": "instance_name", "END_TIME": "end_time",
        "TOTAL_IOPS_AVG": "total_iops_avg", "TOTAL_IOPS_MAX": "total_iops_max",
        "TOTAL_MBPS_AVG": "total_mbps_avg", "TOTAL_MBPS_MAX": "total_mbps_max",
        "CPU_USAGE_PER_SEC_AVG": "cpu_usage_per_sec_avg",
        "CPU_USAGE_PER_SEC_MAX": "cpu_usage_per_sec_max",
        "HOST_CPU_UTIL_PCT_AVG": "host_cpu_util_pct_avg",
        "HOST_CPU_UTIL_PCT_MAX": "host_cpu_util_pct_max",
    }
    table = df.rename(columns={old: new for old, new in rename_map.items() if old in df.columns}).copy()
    columns = ["cluster", "host_name", "db_name", "instance_name", "end_time", "total_iops_avg", "total_iops_max", "total_mbps_avg", "total_mbps_max", "cpu_usage_per_sec_avg", "cpu_usage_per_sec_max", "host_cpu_util_pct_avg", "host_cpu_util_pct_max"]
    table = ensure_columns(table, columns)[columns].copy()
    table["end_time"] = pd.to_datetime(table["end_time"], errors="coerce")
    for column in columns[5:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table


def normalize_db_memory_history(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DB SGA/PGA AWR history rows for charts."""

    rename_map = {
        "Cluster": "cluster", "HOST_NAME": "host_name", "DB_NAME": "db_name",
        "INSTANCE_NAME": "instance_name", "END_TIME": "end_time",
        "SGA_TARGET_GB": "sga_target_gb", "SGA_MAX_SIZE_GB": "sga_max_size_gb",
        "SGA_USED_GB": "sga_used_gb", "PGA_AGGREGATE_TARGET_GB": "pga_aggregate_target_gb",
        "PGA_AGGREGATE_LIMIT_GB": "pga_aggregate_limit_gb", "PGA_ALLOCATED_GB": "pga_allocated_gb",
        "PGA_USED_GB": "pga_used_gb", "PGA_FREEABLE_GB": "pga_freeable_gb",
        "PGA_MAX_ALLOCATED_GB": "pga_max_allocated_gb",
    }
    table = df.rename(columns={old: new for old, new in rename_map.items() if old in df.columns}).copy()
    columns = ["cluster", "host_name", "db_name", "instance_name", "end_time", "sga_target_gb", "sga_max_size_gb", "sga_used_gb", "pga_aggregate_target_gb", "pga_aggregate_limit_gb", "pga_allocated_gb", "pga_used_gb", "pga_freeable_gb", "pga_max_allocated_gb"]
    table = ensure_columns(table, columns)[columns].copy()
    table["end_time"] = pd.to_datetime(table["end_time"], errors="coerce")
    for column in columns[5:]:
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table

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

    health = apply_global_filters(normalize_health(health_df), filters)
    asm = apply_global_filters(normalize_asm(asm_df), filters)
    hugepages = apply_global_filters(normalize_hugepages(huge_df), filters)
    filesystems = apply_global_filters(explode_filesystems(os_df), filters)
    db_resources = apply_global_filters(normalize_db_resources(db_df), filters)
    db_errors = apply_global_filters(normalize_db_resource_errors(db_errors_df), filters)

    st.title("Executive Exadata Resource Cockpit")
    st.caption("Executive risk, capacity, and action view from local collector output only.")
    render_kpis(health, asm, hugepages, db_resources, db_errors)

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

    table = ensure_columns(df, columns + ["imageinfo_path", "imageinfo_json"])[columns + ["imageinfo_path", "imageinfo_json"]].copy()
    imageinfo_values = table[["imageinfo_path", "imageinfo_json"]].fillna("").astype(str)
    missing_imageinfo = imageinfo_values.apply(lambda row: all(value.strip() in {"", "{}", "[]", "<NA>", "nan"} for value in row), axis=1)
    table["missing_imageinfo"] = missing_imageinfo
    table["warning_level"] = table["warning_level"].where(~missing_imageinfo, "WARNING")
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
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


def _render_db_perf_filters(table: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    filtered = table.copy()
    col1, col2, col3 = st.columns(3)
    for column, label, container in [("cluster", "Cluster", col1), ("db_name", "DB name", col2), ("instance_name", "Instance", col3)]:
        values = sorted({str(v) for v in filtered[column].dropna() if str(v).strip()}) if column in filtered.columns else []
        selected = container.multiselect(label, values, default=[], key=f"{key_prefix}_{column}")
        if selected:
            filtered = filtered[filtered[column].astype(str).isin(selected)]
    return _render_date_filter(filtered, key_prefix)


def render_db_performance_page(filters: dict[str, list[str]]) -> None:
    st.title("DB Performance")
    st.caption("Uses DBA_HIST_SYSMETRIC_SUMMARY AWR data; ensure Oracle Diagnostics Pack licensing before enabling collection.")
    df, path = read_output("db_performance")
    show_source(path)
    table = apply_global_filters(normalize_db_performance(df), filters)
    if table.empty:
        st.warning("No db_performance output found in output/.")
        return
    table = _render_db_perf_filters(table, "db_perf")
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


def render_db_memory_history_page(filters: dict[str, list[str]]) -> None:
    st.title("DB Memory History")
    st.caption("Uses DBA_HIST_* AWR memory views; ensure Oracle Diagnostics Pack licensing before enabling collection.")
    df, path = read_output("db_memory_history")
    show_source(path)
    table = apply_global_filters(normalize_db_memory_history(df), filters)
    if table.empty:
        st.warning("No db_memory_history output found in output/.")
        return
    table = _render_db_perf_filters(table, "db_mem")
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.line(table, x="end_time", y="sga_used_gb", color="db_name", line_dash="instance_name", title="SGA_USED_GB over time"), use_container_width=True)
    with c2:
        st.plotly_chart(px.line(table, x="end_time", y="pga_allocated_gb", color="db_name", line_dash="instance_name", title="PGA_ALLOCATED_GB over time"), use_container_width=True)
    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(px.line(table, x="end_time", y="pga_used_gb", color="db_name", line_dash="instance_name", title="PGA_USED_GB over time"), use_container_width=True)
    with c4:
        sga_long = table.melt(id_vars=["end_time", "db_name", "instance_name"], value_vars=["sga_target_gb", "sga_used_gb"], var_name="metric", value_name="gb")
        st.plotly_chart(px.line(sga_long, x="end_time", y="gb", color="db_name", line_dash="metric", title="SGA_TARGET_GB vs SGA_USED_GB"), use_container_width=True)
    pga_long = table.melt(id_vars=["end_time", "db_name", "instance_name"], value_vars=["pga_aggregate_limit_gb", "pga_allocated_gb"], var_name="metric", value_name="gb")
    st.plotly_chart(px.line(pga_long, x="end_time", y="gb", color="db_name", line_dash="metric", title="PGA_AGGREGATE_LIMIT_GB vs PGA_ALLOCATED_GB"), use_container_width=True)
    st.dataframe(table, use_container_width=True, hide_index=True)

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
    elif page == "DB Memory History":
        render_db_memory_history_page(filters)
    elif page == "Raw Data Explorer":
        render_raw_data_page()


if __name__ == "__main__":
    main()
