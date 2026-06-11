"""ASM Analytics page.

ASM ``v$asm_diskgroup`` reports TOTAL_MB / FREE_MB as **raw** capacity
(sum of all disks, mirror copies included). On HIGH redundancy that's 3x
inflated relative to what a DBA can actually put in the diskgroup. This
page shows usable capacity as the primary view (Usable Total / Used /
Free TB), with the raw figures kept side-by-side for hardware context.

Usable Free comes from ``USABLE_FILE_MB`` (already accounts for both
mirror factor and rebalance reserve). Usable Total/Used are raw / mirror.
"""

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


# Detail-table column layout. Usable columns are the primary capacity view;
# raw (sum-of-all-disks) columns sit to the right for hardware context.
DISKGROUP_DETAIL_COLUMNS = [
    {"id": "cluster", "name": "CLUSTER", "type": "text"},
    {"id": "diskgroup_name", "name": "DISKGROUP", "type": "strong"},
    {"id": "type", "name": "REDUNDANCY", "type": "type_badge"},
    {"id": "state", "name": "STATE", "type": "state_badge"},
    {"id": "usable_used_tb", "name": "USABLE USED TB", "type": "number", "decimals": 2},
    {"id": "usable_free_tb", "name": "USABLE FREE TB", "type": "number", "decimals": 2},
    {"id": "usable_total_tb", "name": "USABLE TOTAL TB", "type": "number", "decimals": 2},
    {"id": "used_pct", "name": "% USED", "type": "progress"},
    {"id": "used_tb", "name": "RAW USED TB", "type": "number", "decimals": 2},
    {"id": "free_tb", "name": "RAW FREE TB", "type": "number", "decimals": 2},
    {"id": "total_tb", "name": "RAW TOTAL TB", "type": "number", "decimals": 2},
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

    # Raw totals (sum of all disks across mirror copies).
    raw_total = pd.to_numeric(df["total_tb"], errors="coerce").sum(skipna=True)
    raw_free = pd.to_numeric(df["free_tb"], errors="coerce").sum(skipna=True)
    # Usable: post-redundancy from the detail view, which already mapped
    # redundancy type -> mirror factor per diskgroup.
    usable_total = pd.to_numeric(detail_df["usable_total_tb"], errors="coerce").sum(skipna=True)
    usable_used = pd.to_numeric(detail_df["usable_used_tb"], errors="coerce").sum(skipna=True)
    usable_free = pd.to_numeric(df["usable_tb"], errors="coerce").sum(skipna=True)
    critical = int((df["warning_level"].map(normalize_severity) == "CRITICAL").sum())
    warning = int((df["warning_level"].map(normalize_severity) == "WARNING").sum())

    cards = kpi_row(
        [
            kpi_card("Diskgroups", len(df), "INFO"),
            kpi_card("Usable Total (TB)", f"{usable_total:,.2f}", "INFO"),
            kpi_card("Usable Used (TB)", f"{usable_used:,.2f}", "INFO"),
            kpi_card("Usable Free (TB)", f"{usable_free:,.2f}", "INFO"),
            kpi_card("Raw Total (TB)", f"{raw_total:,.2f}", "INFO",
                     hint="sum of all disks, mirror copies included"),
            kpi_card("Raw Free (TB)", f"{raw_free:,.2f}", "INFO"),
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
        subtitle=(
            "Usable Free comes from ASM USABLE_FILE_MB (accounts for mirror "
            "factor + rebalance reserve). Usable Total/Used are derived as "
            "Raw / mirror_factor (HIGH=3, NORMAL=2, EXTERNAL=1, FLEX/EXTEND=2)."
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
    top_usable_used = section_panel(
        "Top diskgroups by usable used TB",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df,
                "usable_used_tb",
                "diskgroup_label",
                "Top diskgroups by usable used TB",
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
            html.Div([top_pct, top_usable_used], className="panel-grid"),
            risk_panel,
        ]
    )
