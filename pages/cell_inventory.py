"""Cell Inventory page.

Surfaces ``output/cell_inventory.{json,csv}`` (successful per-cell rows) and
``output/cell_inventory_errors.{json,csv}`` (failed cell access). Shows cell
count and version by cluster, the access method used (exacli/dcli/direct),
flash-cache and hard-disk totals in TB, and a failed-access table so mixed
on-prem/OCI estates can see exactly which cells could not be reached and why.
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
from services.normalizers import (
    normalize_cell_inventory,
    normalize_cell_inventory_errors,
)

dash.register_page(__name__, path="/storage/cells", name="Cell Inventory")


def layout():
    return html.Div(id="cell-inventory-content")


def _sum(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").sum(skipna=True))


@callback(
    Output("cell-inventory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_cell_inventory(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    cells = apply_cluster_filter(normalize_cell_inventory(read_output("cell_inventory")), selected)
    errors = apply_cluster_filter(
        normalize_cell_inventory_errors(read_output("cell_inventory_errors")), selected
    )

    if cells.empty and errors.empty:
        return empty_state(
            "No cell inventory output found under output/",
            "python main.py --config config/your-config.yaml",
        )

    clusters = int(cells["cluster"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if not cells.empty else 0
    cell_count = len(cells)
    flash_tb = _sum(cells, "flash_cache_tb")
    hard_tb = _sum(cells, "hard_disk_tb")
    flash_disk_tb = _sum(cells, "flash_disk_tb")
    methods = (
        ", ".join(sorted(cells["cell_access_method"].dropna().astype(str).unique()))
        if not cells.empty else "—"
    )
    failed = len(errors)

    cards = kpi_row([
        kpi_card("Clusters", clusters, "INFO"),
        kpi_card("Cells", cell_count, "INFO"),
        kpi_card("Access method", methods or "—", "INFO"),
        kpi_card("Flash cache (TB)", f"{flash_tb:,.1f}", "INFO"),
        kpi_card("Hard disk (TB)", f"{hard_tb:,.1f}", "INFO"),
        kpi_card("Flash disk (TB)", f"{flash_disk_tb:,.1f}", "INFO"),
        kpi_card("Failed cell access", failed, "CRITICAL" if failed else "OK"),
    ])

    children = [cards]

    if not cells.empty:
        # Cell count by cluster.
        by_cluster = (
            cells.groupby("cluster", dropna=False)
            .agg(
                cells=("cell_name", "nunique"),
                flash_cache_tb=("flash_cache_tb", "sum"),
                hard_disk_tb=("hard_disk_tb", "sum"),
            )
            .reset_index()
        )
        for col in ("flash_cache_tb", "hard_disk_tb"):
            by_cluster[col] = pd.to_numeric(by_cluster[col], errors="coerce").round(2)
        children.append(section_panel("Cells by cluster", data_table(by_cluster, "cell-by-cluster")))

        # Version spread by cluster (drift signal).
        version_view = (
            cells.groupby("cluster", dropna=False)["cell_version"]
            .agg(lambda s: ", ".join(sorted({str(v) for v in s.dropna() if str(v).strip()})) or "—")
            .reset_index()
            .rename(columns={"cell_version": "cell_versions"})
        )
        children.append(section_panel("Cell version by cluster", data_table(version_view, "cell-version-by-cluster")))

        chart_df = cells.assign(
            cell_label=cells["cluster"].fillna("?").astype(str) + " / " + cells["cell_name"].fillna("?").astype(str)
        )
        top_flash = section_panel(
            "Top cells by flash cache",
            dcc.Graph(figure=horizontal_top_bar(chart_df, "flash_cache_tb", "cell_label", "Flash cache (TB)")),
        )
        top_hard = section_panel(
            "Top cells by hard disk",
            dcc.Graph(figure=horizontal_top_bar(chart_df, "hard_disk_tb", "cell_label", "Hard disk (TB)")),
        )
        children.append(html.Div([top_flash, top_hard], className="panel-grid"))
        children.append(section_panel("Cell detail", data_table(cells, "cell-detail-table")))

    # Failed cell access table — important for mixed access models.
    children.append(section_panel(
        "Failed cell access",
        data_table(errors, "cell-errors-table") if not errors.empty
        else html.Div("All cells reached successfully.", className="kpi-hint"),
    ))

    return html.Div(children)
