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
    "CRITICAL": "#ffebee",
    "WARNING": "#fff8e1",
    "OK": "#e8f5e9",
}


st.set_page_config(
    page_title="Exadata Resource Intelligence Collector",
    page_icon="📊",
    layout="wide",
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


def apply_warning_style(df: pd.DataFrame) -> pd.DataFrame:
    """Return a simple dataframe style map for warning levels."""

    if "warning_level" not in df.columns:
        return pd.DataFrame("", index=df.index, columns=df.columns)

    styles = []
    for _, row in df.iterrows():
        level = normalize_warning_level(row.get("warning_level"))
        color = LEVEL_COLORS.get(level, "")
        styles.append([f"background-color: {color}" if color else "" for _ in df.columns])
    return pd.DataFrame(styles, index=df.index, columns=df.columns)


def show_source(path: Path | None) -> None:
    """Show source file information for a dashboard section."""

    if path is None:
        st.info("No local output file found for this section yet.")
    else:
        st.caption(f"Source: {path}")


def select_filter(df: pd.DataFrame, column: str, label: str) -> list[Any]:
    """Render a multiselect filter if a column exists."""

    if column not in df.columns or df.empty:
        return []
    values = sorted(v for v in df[column].dropna().unique().tolist() if str(v) != "")
    return st.multiselect(label, values, default=values)


def filtered_dataframe(df: pd.DataFrame, filters: dict[str, list[Any]]) -> pd.DataFrame:
    """Apply dashboard multiselect filters."""

    filtered = df.copy()
    for column, selected in filters.items():
        if selected and column in filtered.columns:
            filtered = filtered[filtered[column].isin(selected)]
    return filtered


def render_health_tab() -> None:
    st.subheader("Executive Health")
    df, path = read_output("health_summary")
    show_source(path)

    if df.empty:
        st.warning("Run the collector first to generate output/health_summary.json or output/health_summary.csv.")
        return

    df = ensure_columns(df, ["cluster", "host", "warning_level", "category"])
    df["warning_level"] = df["warning_level"].map(normalize_warning_level)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total clusters", int(df["cluster"].dropna().nunique()))
    col2.metric("Total hosts", int(df["host"].dropna().nunique()))
    col3.metric("CRITICAL", int((df["warning_level"] == "CRITICAL").sum()))
    col4.metric("WARNING", int((df["warning_level"] == "WARNING").sum()))
    col5.metric("OK", int((df["warning_level"] == "OK").sum()))

    with st.expander("Filters", expanded=True):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            clusters = select_filter(df, "cluster", "Cluster")
        with fc2:
            hosts = select_filter(df, "host", "Host")
        with fc3:
            levels = select_filter(df, "warning_level", "Warning level")
        with fc4:
            categories = select_filter(df, "category", "Category")

    filtered = filtered_dataframe(
        df,
        {
            "cluster": clusters,
            "host": hosts,
            "warning_level": levels,
            "category": categories,
        },
    )
    st.dataframe(filtered.style.apply(apply_warning_style, axis=None), use_container_width=True)


def render_asm_tab() -> None:
    st.subheader("ASM Capacity")
    df, path = read_output("asm_diskgroups")
    show_source(path)

    columns = ["cluster", "host", "diskgroup_name", "total_tb", "free_tb", "usable_tb", "used_pct", "warning_level"]
    if df.empty:
        st.warning("No asm_diskgroups output found in output/.")
        return

    table = ensure_columns(df, columns)[columns].copy()
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    for column in ["total_tb", "free_tb", "usable_tb", "used_pct"]:
        table[column] = pd.to_numeric(table[column], errors="coerce")

    st.dataframe(table.style.apply(apply_warning_style, axis=None), use_container_width=True)

    chart_data = table.dropna(subset=["cluster", "diskgroup_name", "used_pct"]).copy()
    if not chart_data.empty:
        chart_data["cluster_diskgroup"] = chart_data["cluster"].astype(str) + " / " + chart_data["diskgroup_name"].astype(str)
        fig = px.bar(
            chart_data,
            x="cluster_diskgroup",
            y="used_pct",
            color="warning_level",
            hover_data=["cluster", "host", "diskgroup_name", "free_tb", "usable_tb"],
            title="ASM used percentage by cluster/diskgroup",
            labels={"cluster_diskgroup": "Cluster / Diskgroup", "used_pct": "Used %"},
        )
        fig.update_yaxes(range=[0, max(100, float(chart_data["used_pct"].max()))])
        st.plotly_chart(fig, use_container_width=True)


def render_hugepages_tab() -> None:
    st.subheader("HugePages")
    df, path = read_output("hugepages")
    show_source(path)

    columns = [
        "cluster",
        "host",
        "hugepages_total",
        "hugepages_free",
        "hugepages_free_pct",
        "hugepages_used_pct",
        "warning_level",
    ]
    if df.empty:
        st.warning("No hugepages output found in output/.")
        return

    table = ensure_columns(df, columns)[columns].copy()
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    st.dataframe(table.style.apply(apply_warning_style, axis=None), use_container_width=True)


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
    return pd.DataFrame(rows)


def render_host_inventory_tab() -> None:
    st.subheader("Host Inventory")
    df, path = read_output("os_inventory")
    show_source(path)

    if df.empty:
        st.warning("No os_inventory output found in output/.")
        return

    summary_columns = ["cluster", "host", "hostname", "status", "uptime", "cpu_json", "meminfo_json", "cpu", "meminfo"]
    st.markdown("#### CPU and memory summary")
    st.dataframe(ensure_columns(df, summary_columns)[summary_columns], use_container_width=True)

    st.markdown("#### Filesystem usage")
    filesystems = explode_filesystems(df)
    if filesystems.empty:
        st.info("No filesystem details were available in os_inventory.")
    else:
        st.dataframe(filesystems, use_container_width=True)


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


def render_db_inventory_tab() -> None:
    st.subheader("DB Inventory")
    df, path = read_output("db_inventory")
    show_source(path)

    if df.empty:
        st.warning("No db_inventory output found in output/.")
        return

    st.dataframe(summarize_db_inventory(df), use_container_width=True)


def render_version_inventory_tab() -> None:
    st.subheader("Version Inventory")
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
    missing_imageinfo = imageinfo_values.apply(lambda row: all(value.strip() in {"", "{}", "[]"} for value in row), axis=1)
    table["warning_level"] = table["warning_level"].where(~missing_imageinfo, "WARNING")
    table["warning_level"] = table["warning_level"].map(normalize_warning_level)
    table = table[columns]
    st.dataframe(table.style.apply(apply_warning_style, axis=None), use_container_width=True)


def render_raw_data_tab() -> None:
    st.subheader("Raw Data Explorer")
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
    st.title("Exadata Resource Intelligence Collector")
    st.caption("Phase 1 local dashboard. Reads JSON/CSV files from output/ only; no server connections are made.")

    tabs = st.tabs(
        [
            "Executive Health",
            "Host Inventory",
            "ASM Capacity",
            "HugePages",
            "DB Inventory",
            "Version Inventory",
            "Raw Data Explorer",
        ]
    )

    with tabs[0]:
        render_health_tab()
    with tabs[1]:
        render_host_inventory_tab()
    with tabs[2]:
        render_asm_tab()
    with tabs[3]:
        render_hugepages_tab()
    with tabs[4]:
        render_db_inventory_tab()
    with tabs[5]:
        render_version_inventory_tab()
    with tabs[6]:
        render_raw_data_tab()


if __name__ == "__main__":
    main()
