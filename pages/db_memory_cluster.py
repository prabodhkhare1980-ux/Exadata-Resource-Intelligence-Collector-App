"""DB Memory Cluster Rollup page.

Surfaces ``output/db_memory_cluster_summary.{json,csv}``: per-cluster
database/instance counts, avg/max SGA used, and the most-recent total
SGA used / PGA allocated across each cluster. The collector already
computes this rollup; this page makes it visible.
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
from services.normalizers import normalize_db_memory_cluster_summary

dash.register_page(__name__, path="/db/memory-cluster", name="DB Memory Cluster Rollup")


def layout():
    return html.Div(id="db-memory-cluster-content")


def _sum_numeric(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").sum(skipna=True))


@callback(
    Output("db-memory-cluster-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_memory_cluster(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("db_memory_cluster_summary")
    if raw.empty:
        return empty_state(
            "DB memory cluster summary output not found",
            "python main.py --collectors db_performance",
        )
    df = normalize_db_memory_cluster_summary(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No DB memory cluster rows match the current cluster filter")

    clusters = int(df["cluster"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    total_dbs = int(_sum_numeric(df, "database_count"))
    total_instances = int(_sum_numeric(df, "instance_count"))
    total_latest_sga = _sum_numeric(df, "total_latest_sga_used_gb")
    total_latest_pga = _sum_numeric(df, "total_latest_pga_used_gb")
    total_latest_pga_alloc = _sum_numeric(df, "total_latest_pga_allocated_gb")
    max_sga = pd.to_numeric(df.get("max_sga_used_gb"), errors="coerce").max(skipna=True)

    cards = kpi_row([
        kpi_card("Clusters", clusters, "INFO"),
        kpi_card("Databases", f"{total_dbs:,}", "INFO"),
        kpi_card("Instances", f"{total_instances:,}", "INFO"),
        kpi_card("Latest SGA used (GB, sum)", f"{total_latest_sga:,.1f}", "INFO"),
        kpi_card("Latest PGA used (GB, sum)", f"{total_latest_pga:,.1f}", "INFO"),
        kpi_card("Latest PGA allocated (GB, sum)", f"{total_latest_pga_alloc:,.1f}", "INFO"),
        kpi_card(
            "Peak per-instance SGA used (GB)",
            f"{max_sga:,.1f}" if pd.notna(max_sga) else "—",
            "INFO",
        ),
    ])

    chart_df = df.assign(cluster_label=df["cluster"].astype(str))
    top_sga = section_panel(
        "Top clusters by latest SGA used",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "total_latest_sga_used_gb", "cluster_label",
                "Top clusters by latest SGA used (GB)",
            )
        ),
    )
    top_pga = section_panel(
        "Top clusters by latest PGA allocated",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "total_latest_pga_allocated_gb", "cluster_label",
                "Top clusters by latest PGA allocated (GB)",
            )
        ),
    )

    table = df.copy()
    for col in (
        "avg_sga_used_gb", "max_sga_used_gb",
        "total_latest_sga_used_gb", "total_latest_pga_used_gb",
        "total_latest_pga_allocated_gb",
    ):
        if col in table.columns:
            table[col] = pd.to_numeric(table[col], errors="coerce").round(2)

    detail_panel = section_panel(
        "Cluster memory rollup", data_table(table, "db-memory-cluster-table"),
    )

    return html.Div([
        cards,
        html.Div([top_sga, top_pga], className="panel-grid"),
        detail_panel,
    ])
