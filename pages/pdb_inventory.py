"""PDB Inventory page (Multitenant license posture).

Surfaces ``output/pdb_inventory.{json,csv}`` produced by the DB capacity
collector. Shows total/open/mounted/restricted PDB counts by cluster,
PDBs-per-CDB ranking with a "review" flag for CDBs over the EE
Multitenant free-PDB allowance, top PDBs by size, open-mode breakdown,
and a filterable detail table.

A non-CDB DB shows up in the source file as a single informational row
with ``collection_error='no_pluggable_databases'`` and an empty
``PDB_NAME``; the normalizer drops those so the analytics here count
real PDBs only.
"""

from __future__ import annotations

import dash
import pandas as pd
import plotly.express as px
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.charts import horizontal_top_bar
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import (
    build_pdb_cluster_rollup,
    build_pdbs_per_cdb,
    normalize_pdb_inventory,
)

dash.register_page(__name__, path="/db/pdbs", name="PDB Inventory")


def layout():
    return html.Div(id="pdb-inventory-content")


def _open_mode_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "open_mode" not in df.columns:
        return pd.DataFrame(columns=["open_mode", "pdbs"])
    counts = (
        df["open_mode"].fillna("UNKNOWN").astype(str).str.upper()
        .value_counts()
        .rename_axis("open_mode")
        .reset_index(name="pdbs")
    )
    return counts


@callback(
    Output("pdb-inventory-content", "children"),
    Input("global-filter-state", "data"),
)
def render_pdb_inventory(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("pdb_inventory")
    if raw.empty:
        return empty_state(
            "PDB inventory output not found",
            "python main.py --collectors db_capacity",
        )

    df = apply_cluster_filter(normalize_pdb_inventory(raw), selected)
    if df.empty:
        return empty_state(
            "No PDB rows match the current cluster filter "
            "(non-CDB databases are excluded from this view)."
        )

    clusters = int(
        df["cluster"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    cdbs = int(df["cdb_name"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    pdbs = int(df["pdb_name"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    total_size = float(pd.to_numeric(df["total_size_gb"], errors="coerce").sum(skipna=True))
    open_modes = df["open_mode"].astype(str).str.upper()
    open_count = int(((open_modes == "READ WRITE") | (open_modes == "READ ONLY")).sum())
    mounted = int((open_modes == "MOUNTED").sum())
    restricted = int(df["restricted"].astype(str).str.upper().eq("YES").sum())

    # Top consumer for the KPI tile.
    top_consumer = "—"
    sized = df.dropna(subset=["total_size_gb"]).sort_values("total_size_gb", ascending=False)
    if not sized.empty:
        row = sized.iloc[0]
        top_consumer = f"{row['cdb_name']}/{row['pdb_name']} ({row['total_size_gb']:.1f} GB)"

    cards = kpi_row([
        kpi_card("Clusters", clusters, "INFO"),
        kpi_card("CDBs (with PDBs)", cdbs, "INFO"),
        kpi_card("PDBs (distinct)", pdbs, "INFO"),
        kpi_card("Total PDB size (GB)", f"{total_size:,.1f}", "INFO"),
        kpi_card("Open PDBs", open_count, "INFO"),
        kpi_card("Mounted PDBs", mounted, "WARNING" if mounted else "OK"),
        kpi_card("Restricted PDBs", restricted, "WARNING" if restricted else "OK"),
        kpi_card("Top PDB", top_consumer, "INFO"),
    ])

    # Per-cluster Multitenant rollup.
    rollup = build_pdb_cluster_rollup(df)
    rollup_panel = section_panel(
        "Per-cluster Multitenant rollup",
        data_table(rollup, "pdb-cluster-rollup")
        if not rollup.empty
        else html.Div("No cluster rollup available.", className="kpi-hint"),
    )

    # PDBs-per-CDB ranking (license posture).
    per_cdb = build_pdbs_per_cdb(df)
    per_cdb_panel = section_panel(
        "PDBs per CDB (Multitenant license posture)",
        html.Div([
            html.Div(
                "CDBs with more than 3 PDBs on Enterprise Edition typically "
                "require Multitenant licensing -- those rows are flagged for review.",
                className="kpi-hint",
            ),
            data_table(per_cdb, "pdbs-per-cdb"),
        ]),
    )

    # Top PDBs by size.
    chart_df = df.assign(
        pdb_label=df["cluster"].fillna("?").astype(str)
        + " / " + df["cdb_name"].fillna("?").astype(str)
        + " / " + df["pdb_name"].fillna("?").astype(str)
    )
    top_size_panel = section_panel(
        "Top PDBs by total size",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "total_size_gb", "pdb_label", "Top PDBs by total size (GB)"
            )
        ),
    )

    # Open-mode breakdown.
    om = _open_mode_breakdown(df)
    if om.empty:
        open_mode_panel = section_panel(
            "Open-mode distribution",
            html.Div("No open-mode data.", className="kpi-hint"),
        )
    else:
        fig = px.pie(
            om, names="open_mode", values="pdbs",
            title="PDB open-mode distribution", template="plotly_dark",
            hole=0.4,
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        open_mode_panel = section_panel(
            "Open-mode distribution", dcc.Graph(figure=fig)
        )

    # Detail table.
    detail_columns = [
        "cluster", "cdb_name", "pdb_name", "con_id", "open_mode",
        "restricted", "total_size_gb", "collected_at",
    ]
    detail = df[[c for c in detail_columns if c in df.columns]].copy()
    if "total_size_gb" in detail.columns:
        detail["total_size_gb"] = (
            pd.to_numeric(detail["total_size_gb"], errors="coerce").round(2)
        )
    if "con_id" in detail.columns:
        detail["con_id"] = pd.to_numeric(detail["con_id"], errors="coerce").astype("Int64")
    detail_panel = section_panel("PDB detail", data_table(detail, "pdb-detail-table"))

    return html.Div([
        cards,
        rollup_panel,
        per_cdb_panel,
        html.Div([top_size_panel, open_mode_panel], className="panel-grid"),
        detail_panel,
    ])
