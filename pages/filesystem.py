"""Filesystem Analytics page.

Surfaces ``df -h`` filesystem data captured by the OS collector with the
same dashboard treatment as the rest of the app: a KPI row, top-N charts,
a per-host rollup, and a severity-styled detail table. Sizes are parsed
from the ``df -h`` text tokens (``98G`` / ``1.2T`` / ``500M``) into
numeric GB so we can aggregate and rank.
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
    build_filesystem_host_rollup,
    explode_filesystems,
    normalize_severity,
)

dash.register_page(__name__, path="/os/filesystem", name="Filesystem Analytics")


def layout():
    return html.Div(id="filesystem-content")


def _sum(series: pd.Series) -> float:
    return float(pd.to_numeric(series, errors="coerce").sum(skipna=True))


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
    df = apply_cluster_filter(explode_filesystems(raw), selected)
    if df.empty:
        return empty_state("No filesystem rows match the current cluster filter")

    levels = df["warning_level"].map(normalize_severity)
    critical = int((levels == "CRITICAL").sum())
    warning = int((levels == "WARNING").sum())
    hosts = int(
        df["host"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    )
    fs_count = len(df)
    total_tb = _sum(df["size_gb"]) / 1024.0
    used_tb = _sum(df["used_gb"]) / 1024.0
    free_tb = _sum(df["available_gb"]) / 1024.0
    avg_pct = float(pd.to_numeric(df["used_pct"], errors="coerce").mean(skipna=True))
    max_pct = float(pd.to_numeric(df["used_pct"], errors="coerce").max(skipna=True))

    cards = kpi_row([
        kpi_card("Hosts", hosts, "INFO"),
        kpi_card("Filesystems", fs_count, "INFO"),
        kpi_card("Total (TB)", f"{total_tb:,.2f}", "INFO"),
        kpi_card("Used (TB)", f"{used_tb:,.2f}", "INFO"),
        kpi_card("Free (TB)", f"{free_tb:,.2f}", "INFO"),
        kpi_card(
            "Avg used %",
            f"{avg_pct:,.1f}" if pd.notna(avg_pct) else "—",
            "WARNING" if pd.notna(avg_pct) and avg_pct >= 80 else "INFO",
        ),
        kpi_card(
            "Max used %",
            f"{max_pct:,.1f}" if pd.notna(max_pct) else "—",
            "CRITICAL" if pd.notna(max_pct) and max_pct >= 90 else
            ("WARNING" if pd.notna(max_pct) and max_pct >= 80 else "INFO"),
        ),
        kpi_card("Critical FS", critical, "CRITICAL" if critical else "OK"),
        kpi_card("Warning FS", warning, "WARNING" if warning else "OK"),
    ])

    # Top-N charts.
    chart_df = df.assign(
        fs_label=df["cluster"].fillna("?").astype(str)
        + " / " + df["host"].fillna("?").astype(str)
        + " : " + df["mount"].fillna("?").astype(str)
    )
    top_pct_panel = section_panel(
        "Top filesystems by used %",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "used_pct", "fs_label", "Top filesystems by used %"
            )
        ),
    )
    top_gb_panel = section_panel(
        "Top filesystems by used GB",
        dcc.Graph(
            figure=horizontal_top_bar(
                chart_df, "used_gb", "fs_label", "Top filesystems by used GB"
            )
        ),
    )

    # Per-host rollup table.
    rollup = build_filesystem_host_rollup(df)
    if not rollup.empty:
        # Surface a synthetic warning_level so the standard severity styling
        # paints the rows that have any critical/warning filesystem.
        rollup["warning_level"] = [
            "CRITICAL" if c else ("WARNING" if w else "OK")
            for c, w in zip(rollup["critical_count"], rollup["warning_count"])
        ]
        for col in ("size_gb", "used_gb", "available_gb"):
            rollup[col] = pd.to_numeric(rollup[col], errors="coerce").round(2)
    rollup_panel = section_panel(
        "Per-host rollup",
        data_table(rollup, "filesystem-host-rollup")
        if not rollup.empty
        else html.Div("No per-host rollup available.", className="kpi-hint"),
    )

    # Detail table: sorted by severity (already done by explode_filesystems).
    detail_columns = [
        "cluster", "host", "filesystem", "type", "mount",
        "size_gb", "used_gb", "available_gb", "used_pct", "warning_level",
    ]
    detail = df[[c for c in detail_columns if c in df.columns]].copy()
    for col in ("size_gb", "used_gb", "available_gb"):
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce").round(2)
    if "used_pct" in detail.columns:
        detail["used_pct"] = pd.to_numeric(detail["used_pct"], errors="coerce").round(1)
    detail_panel = section_panel(
        "Filesystem detail",
        data_table(detail, "filesystem-detail-table"),
    )

    # Risk-only table for triage focus.
    risk = df[levels.isin(["CRITICAL", "WARNING"])].copy()
    risk_panel = section_panel(
        "Risk filesystems",
        data_table(
            risk[[c for c in detail_columns if c in risk.columns]],
            "filesystem-risk-table",
        )
        if not risk.empty
        else html.Div(
            "No filesystems in CRITICAL or WARNING.",
            className="kpi-hint",
        ),
    )

    return html.Div([
        cards,
        html.Div([top_pct_panel, top_gb_panel], className="panel-grid"),
        rollup_panel,
        risk_panel,
        detail_panel,
    ])
