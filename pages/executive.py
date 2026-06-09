"""Executive Cockpit page - high-level KPI overview."""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.filters import apply_cluster_filter
from services.analytics import severity_counts
from services.data_loader import read_output
from services.normalizers import (
    normalize_asm,
    normalize_db_memory_summary,
    normalize_db_performance,
    normalize_hugepages,
    normalize_severity,
)

dash.register_page(__name__, path="/", name="Executive Cockpit")


def layout():
    return html.Div(id="executive-content", className="executive-cockpit")


def _count_unique(df: pd.DataFrame, column: str) -> int:
    if df is None or df.empty or column not in df.columns:
        return 0
    return int(df[column].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())


def _max_numeric(df: pd.DataFrame, column: str) -> float | None:
    if df is None or df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.max())


@callback(
    Output("executive-content", "children"),
    Input("global-filter-state", "data"),
)
def render_executive(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []

    health = read_output("health_summary")
    asm = normalize_asm(read_output("asm_diskgroups"))
    huge = normalize_hugepages(read_output("hugepages"))
    db_resources = read_output("db_resource_details")
    db_mem_summary = normalize_db_memory_summary(read_output("db_memory_history_summary"))
    db_perf = normalize_db_performance(read_output("db_performance"))
    os_inv = read_output("os_inventory")

    health = apply_cluster_filter(health, selected)
    asm = apply_cluster_filter(asm, selected)
    huge = apply_cluster_filter(huge, selected)
    db_resources = apply_cluster_filter(db_resources, selected)
    db_mem_summary = apply_cluster_filter(db_mem_summary, selected)
    db_perf = apply_cluster_filter(db_perf, selected)
    os_inv = apply_cluster_filter(os_inv, selected)

    counts = severity_counts(health["warning_level"]) if "warning_level" in health.columns else severity_counts(pd.Series(dtype=str))

    clusters = _count_unique(
        pd.concat(
            [
                df[["cluster"]] if "cluster" in df.columns else pd.DataFrame()
                for df in (asm, huge, db_resources, db_mem_summary, db_perf, os_inv, health)
            ],
            ignore_index=True,
        ),
        "cluster",
    )
    hosts = _count_unique(
        pd.concat(
            [
                os_inv[["host"]] if "host" in os_inv.columns else pd.DataFrame(),
                huge[["host"]] if "host" in huge.columns else pd.DataFrame(),
                asm[["host"]] if "host" in asm.columns else pd.DataFrame(),
            ],
            ignore_index=True,
        ),
        "host",
    )
    dbs = _count_unique(db_resources, "db_unique_name") or _count_unique(db_resources, "db_name")

    asm_critical = 0
    if "warning_level" in asm.columns:
        asm_critical = int((asm["warning_level"].map(normalize_severity) == "CRITICAL").sum())

    huge_critical = 0
    if "warning_level" in huge.columns:
        huge_critical = int((huge["warning_level"].map(normalize_severity) == "CRITICAL").sum())

    top_memory_consumer = "—"
    if not db_mem_summary.empty and "sga_used_gb_max" in db_mem_summary.columns:
        ranked = db_mem_summary.dropna(subset=["sga_used_gb_max"]).sort_values(
            "sga_used_gb_max", ascending=False
        )
        if not ranked.empty:
            row = ranked.iloc[0]
            top_memory_consumer = f"{row.get('db_name') or row.get('db_unique_name')} ({row['sga_used_gb_max']:.1f} GB)"

    max_db_cpu = _max_numeric(db_perf, "cpu_usage_per_sec_max")
    max_iops = _max_numeric(db_perf, "total_iops_max")

    if (
        health.empty
        and asm.empty
        and huge.empty
        and db_resources.empty
        and db_perf.empty
        and os_inv.empty
    ):
        return empty_state(
            "No collector output found under output/",
            "python main.py --config config/your-config.yaml",
        )

    cards = kpi_row(
        [
            kpi_card("Clusters", clusters, "INFO"),
            kpi_card("Hosts", hosts, "INFO"),
            kpi_card("Databases", dbs, "INFO"),
            kpi_card("Critical findings", counts["CRITICAL"], "CRITICAL" if counts["CRITICAL"] else "OK"),
            kpi_card("Warning findings", counts["WARNING"], "WARNING" if counts["WARNING"] else "OK"),
            kpi_card("ASM critical diskgroups", asm_critical, "CRITICAL" if asm_critical else "OK"),
            kpi_card("HugePages critical hosts", huge_critical, "CRITICAL" if huge_critical else "OK"),
            kpi_card("Top DB memory consumer", top_memory_consumer, "INFO"),
            kpi_card(
                "Max DB CPU per sec",
                f"{max_db_cpu:.2f}" if max_db_cpu is not None else "—",
                "INFO",
            ),
            kpi_card(
                "Max DB total IOPS",
                f"{max_iops:,.0f}" if max_iops is not None else "—",
                "INFO",
            ),
        ]
    )

    note = section_panel(
        "Coverage",
        html.Div(
            [
                html.Div(
                    "Use the cluster filter in the topbar to focus the cockpit on a "
                    "specific Exadata cluster. Deep links per cluster, DB, and host "
                    "will be enabled in a later phase.",
                    className="kpi-hint",
                )
            ]
        ),
    )

    return html.Div([cards, note])
