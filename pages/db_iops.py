"""DB IOPS Analytics page."""

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

dash.register_page(__name__, path="/db/iops", name="DB IOPS Analytics")


def layout():
    return html.Div(id="db-iops-content")


@callback(
    Output("db-iops-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_iops(filter_state: dict | None):
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

    iops_avg_trend = section_panel(
        "Total IOPS avg",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "total_iops_avg", "db_label", "Total IOPS avg"
            )
        ),
    )
    iops_max_trend = section_panel(
        "Total IOPS max",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "total_iops_max", "db_label", "Total IOPS max"
            )
        ),
    )

    summary = apply_cluster_filter(build_db_performance_summary(raw), selected)
    summary = summary.assign(
        db_label=summary["cluster"].astype(str) + " / " + summary["db_name"].astype(str)
    )

    top_consumers = section_panel(
        "Top IOPS consumers",
        dcc.Graph(
            figure=horizontal_top_bar(
                summary, "max_total_iops", "db_label", "Top IOPS consumers (max)"
            )
        ),
    )

    risk = summary.copy()
    if "max_total_iops" in risk.columns:
        risk_max = pd.to_numeric(risk["max_total_iops"], errors="coerce")
        risk = risk[risk_max >= 5000].copy()
    else:
        risk = risk.head(0)
    risk_panel = section_panel(
        "IOPS risk table",
        data_table(risk.drop(columns=["db_label"], errors="ignore"), "db-iops-risk-table")
        if not risk.empty
        else html.Div("No databases above 5,000 max IOPS.", className="kpi-hint"),
    )

    return html.Div(
        [
            html.Div([iops_avg_trend, iops_max_trend], className="panel-grid"),
            top_consumers,
            risk_panel,
        ]
    )
