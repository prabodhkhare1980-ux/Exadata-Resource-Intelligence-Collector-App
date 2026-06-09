"""DB Throughput Analytics page."""

from __future__ import annotations

import dash
import pandas as pd
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, section_panel
from components.charts import horizontal_top_bar, time_series_line
from components.filters import apply_cluster_filter
from components.tables import data_table
from services.data_loader import read_output
from services.normalizers import build_db_performance_summary, normalize_db_performance

dash.register_page(__name__, path="/db/throughput", name="DB Throughput Analytics")


def layout():
    return html.Div(id="db-throughput-content")


@callback(
    Output("db-throughput-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_throughput(filter_state: dict | None):
    selected = (filter_state or {}).get("clusters") or []
    raw = read_output("db_performance")
    if raw.empty:
        return empty_state(
            "DB performance output not found",
            "python main.py --collectors db_performance",
        )
    history = apply_cluster_filter(normalize_db_performance(raw), selected)
    if history.empty:
        return empty_state("No DB performance rows match the current cluster filter")

    history = history.assign(
        db_label=history["cluster"].astype(str) + " / " + history["db_name"].astype(str)
    )

    mbps_avg_trend = section_panel(
        "Total MBPS avg",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "total_mbps_avg", "db_label", "Total MBPS avg"
            )
        ),
    )
    mbps_max_trend = section_panel(
        "Total MBPS max",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "total_mbps_max", "db_label", "Total MBPS max"
            )
        ),
    )

    summary = apply_cluster_filter(build_db_performance_summary(raw), selected)
    summary = summary.assign(
        db_label=summary["cluster"].astype(str) + " / " + summary["db_name"].astype(str)
    )

    top_consumers = section_panel(
        "Top MBPS consumers",
        dcc.Graph(
            figure=horizontal_top_bar(
                summary, "max_total_mbps", "db_label", "Top MBPS consumers (max)"
            )
        ),
    )

    risk = summary.copy()
    if "max_total_mbps" in risk.columns:
        risk_max = pd.to_numeric(risk["max_total_mbps"], errors="coerce")
        risk = risk[risk_max >= 500].copy()
    else:
        risk = risk.head(0)
    risk_panel = section_panel(
        "Throughput risk table",
        data_table(risk.drop(columns=["db_label"], errors="ignore"), "db-throughput-risk-table")
        if not risk.empty
        else html.Div("No databases above 500 MBPS max.", className="kpi-hint"),
    )

    return html.Div(
        [
            html.Div([mbps_avg_trend, mbps_max_trend], className="panel-grid"),
            top_consumers,
            risk_panel,
        ]
    )
