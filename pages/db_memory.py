"""DB Memory Analytics page (Phase 1 - summary view)."""

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
from services.normalizers import normalize_db_memory_summary

dash.register_page(__name__, path="/db/memory", name="DB Memory Analytics")


def layout():
    return html.Div(id="db-memory-content")


@callback(
    Output("db-memory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_memory(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("db_memory_history_summary")
    if raw.empty:
        return empty_state(
            "DB memory analytics summary not found",
            "python main.py --collectors db_performance",
        )
    summary = apply_cluster_filter(normalize_db_memory_summary(raw), selected)
    if summary.empty:
        return empty_state("No DB memory summary rows match the current cluster filter")

    summary = summary.assign(
        db_label=summary["cluster"].astype(str) + " / " + summary["db_name"].astype(str)
    )
    total_sga = pd.to_numeric(summary["sga_used_gb_max"], errors="coerce").sum(skipna=True)
    total_pga = pd.to_numeric(summary["pga_allocated_gb_max"], errors="coerce").sum(skipna=True)

    cards = kpi_row(
        [
            kpi_card("Databases tracked", summary["db_name"].nunique(), "INFO"),
            kpi_card("Total SGA used (GB, max)", f"{total_sga:,.1f}", "INFO"),
            kpi_card("Total PGA allocated (GB, max)", f"{total_pga:,.1f}", "INFO"),
        ]
    )
    top_sga = section_panel(
        "Top SGA consumers",
        dcc.Graph(
            figure=horizontal_top_bar(
                summary, "sga_used_gb_max", "db_label", "Top SGA used GB (max)"
            )
        ),
    )
    top_pga = section_panel(
        "Top PGA consumers",
        dcc.Graph(
            figure=horizontal_top_bar(
                summary, "pga_allocated_gb_max", "db_label", "Top PGA allocated GB (max)"
            )
        ),
    )
    table = section_panel(
        "DB memory summary",
        data_table(summary.drop(columns=["db_label"], errors="ignore"), "db-memory-table"),
    )
    return html.Div([cards, html.Div([top_sga, top_pga], className="panel-grid"), table])
