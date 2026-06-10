"""DB Inventory & Capacity page.

Surfaces per-database resource snapshot collected by ``db_inventory`` (file
``output/db_resource_details.{json,csv}``): DB role, version, RAC layout,
configured SGA/PGA, CPU_COUNT, total/used DB size, and used %.
"""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.charts import horizontal_top_bar
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import normalize_db_resource_details, normalize_severity

dash.register_page(__name__, path="/db/inventory", name="DB Inventory & Capacity")


def layout():
    return html.Div(id="db-inventory-content")


def _sum_numeric(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").sum(skipna=True))


@callback(
    Output("db-inventory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_inventory(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("db_resource_details")
    if raw.empty:
        return empty_state(
            "DB resource details output not found",
            "python main.py --collectors db_inventory",
        )
    df = normalize_db_resource_details(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No DB resource rows match the current cluster filter")

    total_dbs = int(df["db_name"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    total_size = _sum_numeric(df, "db_size_gb")
    total_used = _sum_numeric(df, "used_db_size_gb")
    total_sga = _sum_numeric(df, "sga_target_gb")
    total_pga = _sum_numeric(df, "pga_aggr_target_gb")
    total_cpu = int(_sum_numeric(df, "cpu_count"))
    critical = int((df["warning_level"].map(normalize_severity) == "CRITICAL").sum())

    cards = kpi_row([
        kpi_card("Databases", total_dbs, "INFO"),
        kpi_card("Sum CPU_COUNT", f"{total_cpu:,}", "INFO"),
        kpi_card("Configured SGA target (GB)", f"{total_sga:,.1f}", "INFO"),
        kpi_card("Configured PGA target (GB)", f"{total_pga:,.1f}", "INFO"),
        kpi_card("Total DB size (GB)", f"{total_size:,.1f}", "INFO"),
        kpi_card("Used DB size (GB)", f"{total_used:,.1f}", "INFO"),
        kpi_card("Critical DBs (%used)", critical, "CRITICAL" if critical else "OK"),
    ])

    # Per-cluster rollup for capacity at a glance.
    grouping_cols = [c for c in ("cluster",) if c in df.columns]
    rollup = pd.DataFrame()
    if grouping_cols:
        rollup = (
            df.groupby("cluster", dropna=False)
            .agg(
                databases=("db_name", "nunique"),
                cpu_count_sum=("cpu_count", "sum"),
                sga_target_gb_sum=("sga_target_gb", "sum"),
                pga_aggr_target_gb_sum=("pga_aggr_target_gb", "sum"),
                db_size_gb_sum=("db_size_gb", "sum"),
                used_db_size_gb_sum=("used_db_size_gb", "sum"),
            )
            .reset_index()
        )
        for col in (
            "cpu_count_sum", "sga_target_gb_sum", "pga_aggr_target_gb_sum",
            "db_size_gb_sum", "used_db_size_gb_sum",
        ):
            rollup[col] = pd.to_numeric(rollup[col], errors="coerce").round(1)

    rollup_panel = section_panel(
        "Per-cluster capacity rollup",
        data_table(rollup, "db-inventory-rollup")
        if not rollup.empty
        else html.Div("No cluster rollup available.", className="kpi-hint"),
    )

    chart_df = df.assign(
        db_label=df["cluster"].fillna("?").astype(str) + " / " + df["db_name"].fillna("?").astype(str)
    )
    top_size_panel = section_panel(
        "Top databases by total size",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "db_size_gb", "db_label", "Top databases by total size (GB)"
            )
        ),
    )
    top_used_panel = section_panel(
        "Top databases by used size",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "used_db_size_gb", "db_label", "Top databases by used size (GB)"
            )
        ),
    )
    top_cpu_panel = section_panel(
        "Top databases by CPU_COUNT",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "cpu_count", "db_label", "Top databases by CPU_COUNT"
            )
        ),
    )

    detail_columns = [
        "cluster", "host_name", "db_name", "db_unique_name", "db_role",
        "open_mode", "version", "rac_enabled", "inst_count",
        "cpu_count", "processes",
        "sga_target_gb", "sga_max_size_gb",
        "pga_aggr_target_gb", "pga_aggr_limit_gb",
        "db_size_gb", "used_db_size_gb", "db_used_pct",
        "warning_level",
    ]
    detail = df[[c for c in detail_columns if c in df.columns]].copy()
    for col in ("cpu_count", "inst_count", "processes"):
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce").astype("Int64")
    for col in (
        "sga_target_gb", "sga_max_size_gb",
        "pga_aggr_target_gb", "pga_aggr_limit_gb",
        "db_size_gb", "used_db_size_gb", "db_used_pct",
    ):
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce").round(2)

    detail_panel = section_panel("Database resource detail", data_table(detail, "db-inventory-detail"))

    return html.Div([
        cards,
        rollup_panel,
        html.Div([top_size_panel, top_used_panel], className="panel-grid"),
        top_cpu_panel,
        detail_panel,
    ])
