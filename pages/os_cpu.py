"""OS CPU Analytics page.

Parses ``lscpu`` JSON captured by ``os_inventory`` into per-host CPU
inventory: vCPUs, cores per socket, sockets, threads per core, physical
cores, and CPU model. OS-level CPU **utilization** is not yet collected;
when it is, a time-series panel will be added alongside this static
inventory.
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
from services.normalizers import build_os_cpu_table

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
    table = apply_cluster_filter(build_os_cpu_table(raw), selected)
    if table.empty:
        return empty_state("No OS inventory rows match the current cluster filter")

    cpus_series = pd.to_numeric(table["cpus"], errors="coerce")
    cores_series = pd.to_numeric(table["physical_cores"], errors="coerce")
    failed = table[table["status"].astype(str).str.lower() != "ok"]
    cards = kpi_row([
        kpi_card("Hosts collected", len(table), "INFO"),
        kpi_card("Failed hosts", len(failed), "CRITICAL" if len(failed) else "OK"),
        kpi_card("Total vCPUs", f"{int(cpus_series.sum(skipna=True)):,}", "INFO"),
        kpi_card("Total physical cores", f"{int(cores_series.sum(skipna=True)):,}", "INFO"),
        kpi_card(
            "Max vCPUs on host",
            f"{int(cpus_series.max()):,}" if cpus_series.notna().any() else "—",
            "INFO",
        ),
    ])

    chart_df = table.assign(
        host_label=table["cluster"].fillna("?").astype(str) + " / " + table["host"].fillna("?").astype(str)
    )
    top_cpus = section_panel(
        "Top hosts by vCPUs",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "cpus", "host_label", "Top hosts by vCPUs"
            )
        ),
    )

    detail = section_panel("CPU inventory", data_table(table, "os-cpu-table"))

    note = html.Div(
        "OS-level CPU utilization history is not collected yet. AWR-based DB "
        "CPU and host_cpu_util_pct are available on the DB CPU Analytics page.",
        className="kpi-hint",
    )
    return html.Div([cards, note, top_cpus, detail])
