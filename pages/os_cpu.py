"""OS CPU Analytics page (Phase 1)."""

from __future__ import annotations

import dash
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output

dash.register_page(__name__, path="/os/cpu", name="OS CPU Analytics")


def layout():
    return html.Div(id="os-cpu-content")


@callback(
    Output("os-cpu-content", "children"),
    Input("global-filter-state", "data"),
)
def render_os_cpu(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("os_inventory")
    if raw.empty:
        return empty_state(
            "OS inventory output not found",
            "python main.py --collectors os",
        )
    df = apply_cluster_filter(raw, selected)
    if df.empty:
        return empty_state("No OS inventory rows match the current cluster filter")

    cards = kpi_row([kpi_card("Hosts", df["host"].nunique() if "host" in df.columns else len(df), "INFO")])
    return html.Div([cards, section_panel("OS inventory", data_table(df, "os-cpu-table"))])
