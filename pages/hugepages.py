"""HugePages Analytics page."""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table, detail_table
from services.data_loader import read_output
from services.normalizers import (
    build_hugepages_node_detail,
    normalize_hugepages,
    normalize_severity,
)

dash.register_page(__name__, path="/os/hugepages", name="HugePages Analytics")


NODE_DETAIL_COLUMNS = [
    {"id": "cluster", "name": "CLUSTER", "type": "text"},
    {"id": "host", "name": "HOST", "type": "strong"},
    {"id": "mem_gb", "name": "MEM GB", "type": "number", "decimals": 0},
    {"id": "hp_total_gb", "name": "HP TOTAL GB", "type": "number", "decimals": 0},
    {"id": "hp_used_gb", "name": "HP USED GB", "type": "number", "decimals": 0},
    {"id": "hp_free_gb", "name": "HP FREE GB", "type": "number", "decimals": 0},
    {"id": "hp_used_pct", "name": "HP USED %", "type": "progress"},
    {"id": "hp_alloc_pct_ram", "name": "HP ALLOC % RAM", "type": "progress"},
    {"id": "transparent_hugepages", "name": "THP", "type": "thp"},
    {"id": "timestamp", "name": "TIMESTAMP", "type": "text"},
]


def layout():
    return html.Div(id="hugepages-content")


@callback(
    Output("hugepages-content", "children"),
    Input("global-filter-state", "data"),
)
def render_hugepages(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("hugepages")
    if raw.empty:
        return empty_state(
            "HugePages output not found",
            "python main.py --collectors hugepages",
        )
    os_raw = read_output("os_inventory")

    df = normalize_hugepages(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No HugePages rows match the current cluster filter")

    detail_df = build_hugepages_node_detail(raw, os_raw)
    detail_df = apply_cluster_filter(detail_df, selected)

    total = pd.to_numeric(df["hugepages_total"], errors="coerce").sum(skipna=True)
    free = pd.to_numeric(df["hugepages_free"], errors="coerce").sum(skipna=True)
    used = max(total - free, 0)
    used_pct = pd.to_numeric(df["hugepages_used_pct"], errors="coerce").mean(skipna=True)
    alloc_ram_pct = pd.to_numeric(
        detail_df["hp_alloc_pct_ram"], errors="coerce"
    ).mean(skipna=True)
    thp_enabled = 0
    if "transparent_hugepages" in detail_df.columns:
        thp_enabled = int(
            detail_df["transparent_hugepages"]
            .astype(str)
            .str.lower()
            .apply(lambda raw: "[" in raw and "[never]" not in raw)
            .sum()
        )
    critical = int((df["warning_level"].map(normalize_severity) == "CRITICAL").sum())
    warning = int((df["warning_level"].map(normalize_severity) == "WARNING").sum())

    cards = kpi_row(
        [
            kpi_card("Hosts", len(df), "INFO"),
            kpi_card("HP total (pages)", f"{int(total):,}" if not pd.isna(total) else "—", "INFO"),
            kpi_card("HP used (pages)", f"{int(used):,}" if not pd.isna(used) else "—", "INFO"),
            kpi_card("HP free (pages)", f"{int(free):,}" if not pd.isna(free) else "—", "INFO"),
            kpi_card(
                "Avg used %",
                f"{used_pct:.1f}%" if not pd.isna(used_pct) else "—",
                "INFO",
            ),
            kpi_card(
                "Avg allocated % of RAM",
                f"{alloc_ram_pct:.1f}%" if not pd.isna(alloc_ram_pct) else "—",
                "INFO",
            ),
            kpi_card("THP enabled hosts", thp_enabled, "WARNING" if thp_enabled else "OK"),
            kpi_card("Critical hosts", critical, "CRITICAL" if critical else "OK"),
            kpi_card("Warning hosts", warning, "WARNING" if warning else "OK"),
        ]
    )

    node_detail_panel = section_panel(
        "HUGEPAGES — NODE DETAIL",
        detail_table(
            detail_df,
            "hugepages-node-detail",
            NODE_DETAIL_COLUMNS,
            empty_message="No HugePages rows to display.",
            download_stem="hugepages_node_detail",
        ),
    )

    risk = df[df["warning_level"].map(normalize_severity).isin(["CRITICAL", "WARNING"])]
    risk_panel = section_panel(
        "Risk table",
        data_table(risk, "hugepages-risk-table") if not risk.empty
        else html.Div("No hosts in CRITICAL or WARNING.", className="kpi-hint"),
    )

    return html.Div([cards, node_detail_panel, risk_panel])
