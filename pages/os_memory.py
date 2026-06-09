"""OS Memory Analytics page (Phase 1)."""

from __future__ import annotations

import dash
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output

dash.register_page(__name__, path="/os/memory", name="OS Memory Analytics")


def layout():
    return html.Div(id="os-memory-content")


@callback(
    Output("os-memory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_os_memory(filter_state: dict | None):
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
    return section_panel("OS memory inventory", data_table(df, "os-memory-table"))
