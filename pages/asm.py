"""ASM Analytics page."""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.charts import horizontal_top_bar
from components.filters import apply_cluster_filter
from components.tables import data_table, detail_table
from services.data_loader import read_output
from services.normalizers import (
    build_asm_diskgroup_detail,
    normalize_asm,
    normalize_severity,
)

dash.register_page(__name__, path="/storage/asm", name="ASM Analytics")


DISKGROUP_DETAIL_COLUMNS = [
    {"id": "cluster", "name": "CLUSTER", "type": "text"},
    {"id": "diskgroup_name", "name": "DISKGROUP", "type": "strong"},
    {"id": "type", "name": "TYPE", "type": "type_badge"},
    {"id": "state", "name": "STATE", "type": "state_badge"},
    {"id": "used_tb", "name": "USED TB", "type": "number", "decimals": 2},
    {"id": "free_tb", "name": "FREE TB", "type": "number", "decimals": 2},
    {"id": "total_tb", "name": "TOTAL TB", "type": "number", "decimals": 2},
    {"id": "used_pct", "name": "% USED", "type": "progress"},
    {"id": "timestamp", "name": "TIMESTAMP", "type": "text"},
]


def layout():
    return html.Div(id="asm-content")


@callback(
    Output("asm-content", "children"),
    Input("global-filter-state", "data"),
)
def render_asm(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("asm_diskgroups")
    if raw.empty:
        return empty_state(
            "ASM diskgroup output not found",
            "python main.py --collectors asm_diskgroups",
        )
    df = normalize_asm(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No ASM rows match the current cluster filter")

    detail_df = build_asm_diskgroup_detail(raw)
    detail_df = apply_cluster_filter(detail_df, selected)

    total_tb = pd.to_numeric(df["total_tb"], errors="coerce").sum(skipna=True)
    free_tb = pd.to_numeric(df["free_tb"], errors="coerce").sum(skipna=True)
    used_tb = max(total_tb - free_tb, 0)
    usable_tb = pd.to_numeric(df["usable_tb"], errors="coerce").sum(skipna=True)
    critical = int((df["warning_level"].map(normalize_severity) == "CRITICAL").sum())
    warning = int((df["warning_level"].map(normalize_severity) == "WARNING").sum())

    cards = kpi_row(
        [
            kpi_card("Diskgroups", len(df), "INFO"),
            kpi_card("Total (TB)", f"{total_tb:,.2f}", "INFO"),
            kpi_card("Used (TB)", f"{used_tb:,.2f}", "INFO"),
            kpi_card("Free (TB)", f"{free_tb:,.2f}", "INFO"),
            kpi_card("Usable (TB)", f"{usable_tb:,.2f}", "INFO"),
            kpi_card("Critical diskgroups", critical, "CRITICAL" if critical else "OK"),
            kpi_card("Warning diskgroups", warning, "WARNING" if warning else "OK"),
        ]
    )

    diskgroups_panel = section_panel(
        "DISKGROUPS",
        detail_table(
            detail_df,
            "asm-diskgroups-detail",
            DISKGROUP_DETAIL_COLUMNS,
            empty_message="No ASM diskgroup rows to display.",
            download_stem="asm_diskgroups",
        ),
    )

    chart_df = df.assign(
        diskgroup_label=df["cluster"].fillna("?") + " / " + df["diskgroup_name"].fillna("?")
    )

    top_pct = section_panel(
        "Top diskgroups by used %",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "used_pct", "diskgroup_label", "Top diskgroups by used %"
            )
        ),
    )
    top_tb = section_panel(
        "Top diskgroups by used TB",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df.assign(used_tb_val=chart_df["total_tb"] - chart_df["free_tb"]),
                "used_tb_val",
                "diskgroup_label",
                "Top diskgroups by used TB",
            )
        ),
    )

    risk = df[df["warning_level"].map(normalize_severity).isin(["CRITICAL", "WARNING"])].copy()
    risk_panel = section_panel(
        "Risk table",
        data_table(risk, "asm-risk-table") if not risk.empty
        else html.Div("No diskgroups in CRITICAL or WARNING.", className="kpi-hint"),
    )

    return html.Div(
        [
            cards,
            diskgroups_panel,
            html.Div([top_pct, top_tb], className="panel-grid"),
            risk_panel,
        ]
    )
