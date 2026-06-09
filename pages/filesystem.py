"""Filesystem Analytics page (Phase 1)."""

from __future__ import annotations

import dash
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import explode_filesystems

dash.register_page(__name__, path="/os/filesystem", name="Filesystem Analytics")


def layout():
    return html.Div(id="filesystem-content")


@callback(
    Output("filesystem-content", "children"),
    Input("global-filter-state", "data"),
)
def render_filesystem(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("os_inventory")
    if raw.empty:
        return empty_state(
            "OS inventory output not found",
            "python main.py --collectors os",
        )
    df = explode_filesystems(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No filesystem rows match the current cluster filter")
    return section_panel("Filesystems", data_table(df, "filesystem-table"))
