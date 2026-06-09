"""DB CPU Analytics page."""

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

dash.register_page(__name__, path="/db/cpu", name="DB CPU Analytics")


def layout():
    return html.Div(id="db-cpu-content")


@callback(
    Output("db-cpu-content", "children"),
    Input("global-filter-state", "data"),
)
def render_db_cpu(filter_state: dict | None):
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

    db_cpu_trend = section_panel(
        "DB CPU per sec (avg)",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "cpu_usage_per_sec_avg", "db_label", "DB CPU per sec (avg)"
            )
        ),
    )
    host_cpu_trend = section_panel(
        "Host CPU utilization % (max)",
        dcc.Graph(
            figure=time_series_line(
                history, "end_time", "host_cpu_util_pct_max", "db_label", "Host CPU utilization % (max)"
            )
        ),
    )

    summary = apply_cluster_filter(build_db_performance_summary(raw), selected)
    summary = summary.assign(
        db_label=summary["cluster"].astype(str) + " / " + summary["db_name"].astype(str)
    )

    top_consumers = section_panel(
        "Top DB CPU consumers",
        dcc.Graph(
            figure=horizontal_top_bar(
                summary, "max_db_cpu_per_sec", "db_label", "Top DB CPU consumers"
            )
        ),
    )

    risk = summary.copy()
    if "max_host_cpu_util_pct" in risk.columns:
        risk_max = pd.to_numeric(risk["max_host_cpu_util_pct"], errors="coerce")
        risk = risk[risk_max >= 80].copy()
    else:
        risk = risk.head(0)
    risk_panel = section_panel(
        "CPU risk table",
        data_table(risk.drop(columns=["db_label"], errors="ignore"), "db-cpu-risk-table")
        if not risk.empty
        else html.Div("No databases above 80% max host CPU.", className="kpi-hint"),
    )

    return html.Div(
        [
            html.Div([db_cpu_trend, host_cpu_trend], className="panel-grid"),
            top_consumers,
            risk_panel,
        ]
    )
