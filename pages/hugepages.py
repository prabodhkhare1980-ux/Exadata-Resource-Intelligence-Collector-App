"""HugePages Analytics page."""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import normalize_hugepages, normalize_severity

dash.register_page(__name__, path="/os/hugepages", name="HugePages Analytics")


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
    df = normalize_hugepages(raw)
    df = apply_cluster_filter(df, selected)
    if df.empty:
        return empty_state("No HugePages rows match the current cluster filter")

    total = pd.to_numeric(df["hugepages_total"], errors="coerce").sum(skipna=True)
    free = pd.to_numeric(df["hugepages_free"], errors="coerce").sum(skipna=True)
    used = max(total - free, 0)
    used_pct = pd.to_numeric(df["hugepages_used_pct"], errors="coerce").mean(skipna=True)
    alloc_ram_pct = pd.to_numeric(
        df["hugepages_allocated_pct_of_ram"], errors="coerce"
    ).mean(skipna=True)
    thp_enabled = 0
    if "transparent_hugepages" in df.columns:
        thp_enabled = int(
            df["transparent_hugepages"]
            .astype(str)
            .str.lower()
            .str.contains("never")
            .eq(False)
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

    risk = df[df["warning_level"].map(normalize_severity).isin(["CRITICAL", "WARNING"])]
    risk_panel = section_panel(
        "Risk table",
        data_table(risk, "hugepages-risk-table") if not risk.empty
        else html.Div("No hosts in CRITICAL or WARNING.", className="kpi-hint"),
    )
    full_panel = section_panel("All hosts", data_table(df, "hugepages-full-table"))

    return html.Div([cards, risk_panel, full_panel])
