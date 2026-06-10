"""Fleet Inventory page.

Surfaces ``output/version_inventory.{json,csv}`` — per-host Exadata image
version, kernel, node type, and GI active version + release patch list.
Also flags clusters where image or GI patch is not uniform across hosts
(patch drift indicator) so a DMA can spot compliance gaps at a glance.
"""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import (
    build_cluster_version_drift,
    normalize_severity,
    normalize_version_inventory,
)

dash.register_page(__name__, path="/inventory/fleet", name="Fleet Inventory")


def layout():
    return html.Div(id="fleet-inventory-content")


@callback(
    Output("fleet-inventory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_fleet_inventory(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("version_inventory")
    if raw.empty:
        return empty_state(
            "Version inventory output not found",
            "python main.py --collectors version_inventory",
        )
    df = normalize_version_inventory(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No version inventory rows match the current cluster filter")

    drift = apply_cluster_filter(build_cluster_version_drift(raw), selected)

    clusters = int(df["cluster"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    hosts = int(df["host"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    image_versions = int(
        df["image_version"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    gi_patches = int(
        df["gi_release_patch_string"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    image_drift_clusters = int(drift["image_drift"].sum()) if not drift.empty else 0
    gi_drift_clusters = int(drift["gi_patch_drift"].sum()) if not drift.empty else 0

    cards = kpi_row([
        kpi_card("Clusters", clusters, "INFO"),
        kpi_card("Hosts", hosts, "INFO"),
        kpi_card("Distinct image versions", image_versions, "INFO"),
        kpi_card("Distinct GI patch strings", gi_patches, "INFO"),
        kpi_card(
            "Clusters with image drift", image_drift_clusters,
            "WARNING" if image_drift_clusters else "OK",
        ),
        kpi_card(
            "Clusters with GI patch drift", gi_drift_clusters,
            "WARNING" if gi_drift_clusters else "OK",
        ),
    ])

    drift_view = drift.copy()
    if not drift_view.empty:
        # Map to a generic warning_level column so the severity styling kicks in.
        drift_view["warning_level"] = drift_view["severity"].map(normalize_severity)
    drift_panel = section_panel(
        "Cluster patch drift",
        data_table(drift_view, "fleet-drift-table")
        if not drift_view.empty
        else html.Div("No drift data available.", className="kpi-hint"),
    )

    detail = df.copy()
    detail_panel = section_panel(
        "Per-host image and GI inventory",
        data_table(detail, "fleet-detail-table"),
    )

    return html.Div([cards, drift_panel, detail_panel])
