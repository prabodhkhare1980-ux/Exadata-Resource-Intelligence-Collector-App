"""OS Memory Analytics page.

Parses ``/proc/meminfo`` captured by ``os_inventory`` into per-host
memory totals: MemTotal, MemAvailable, used, swap. Renders KPI tiles,
a top-hosts chart by memory used %, and a detail table.
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
from services.normalizers import build_os_memory_table, normalize_severity

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
    table = apply_cluster_filter(build_os_memory_table(raw), selected)
    if table.empty:
        return empty_state("No OS inventory rows match the current cluster filter")

    total_gb = pd.to_numeric(table["mem_total_gb"], errors="coerce").sum(skipna=True)
    used_gb = pd.to_numeric(table["mem_used_gb"], errors="coerce").sum(skipna=True)
    swap_total_gb = pd.to_numeric(table["swap_total_gb"], errors="coerce").sum(skipna=True)
    swap_used_gb = pd.to_numeric(table["swap_used_gb"], errors="coerce").sum(skipna=True)
    avg_pct = pd.to_numeric(table["mem_used_pct"], errors="coerce").mean(skipna=True)
    critical = int((table["severity"].map(normalize_severity) == "CRITICAL").sum())
    warning = int((table["severity"].map(normalize_severity) == "WARNING").sum())

    cards = kpi_row([
        kpi_card("Hosts", len(table), "INFO"),
        kpi_card("Total RAM (GB)", f"{total_gb:,.0f}", "INFO"),
        kpi_card("Total RAM used (GB)", f"{used_gb:,.0f}", "INFO"),
        kpi_card("Avg used %", f"{avg_pct:,.1f}" if pd.notna(avg_pct) else "—", "INFO"),
        kpi_card("Total swap (GB)", f"{swap_total_gb:,.0f}", "INFO"),
        kpi_card("Swap used (GB)", f"{swap_used_gb:,.0f}", "INFO"),
        kpi_card("Critical hosts", critical, "CRITICAL" if critical else "OK"),
        kpi_card("Warning hosts", warning, "WARNING" if warning else "OK"),
    ])

    chart_df = table.assign(
        host_label=table["cluster"].fillna("?").astype(str) + " / " + table["host"].fillna("?").astype(str)
    )
    top_used_pct = section_panel(
        "Top hosts by memory used %",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "mem_used_pct", "host_label", "Top hosts by memory used %"
            )
        ),
    )

    # Round visible numerics so the table is readable.
    detail = table.copy()
    for col in (
        "mem_total_gb", "mem_free_gb", "mem_available_gb",
        "mem_used_gb", "swap_total_gb", "swap_free_gb", "swap_used_gb",
    ):
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce").round(1)
    # Map severity onto the standard warning_level column for table styling.
    detail["warning_level"] = detail["severity"].map(normalize_severity)

    detail_panel = section_panel(
        "Per-host memory inventory", data_table(detail, "os-memory-table"),
    )

    return html.Div([cards, top_used_pct, detail_panel])
