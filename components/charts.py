"""Plotly Express chart builders shared across pages."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

DARK_TEMPLATE = "plotly_dark"


def _empty_figure(message: str = "No data") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template=DARK_TEMPLATE,
        annotations=[
            dict(
                text=message,
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(color="#94a3b8", size=14),
            )
        ],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    return fig


def horizontal_top_bar(
    df: pd.DataFrame, value_col: str, label_col: str, title: str, n: int = 20
) -> go.Figure:
    """Top-N horizontal bar chart for ``value_col`` ordered descending."""

    if df is None or df.empty or value_col not in df.columns or label_col not in df.columns:
        return _empty_figure(f"No data for {title}")
    table = df.copy()
    table[value_col] = pd.to_numeric(table[value_col], errors="coerce")
    table = table.dropna(subset=[value_col]).sort_values(value_col, ascending=False).head(n)
    if table.empty:
        return _empty_figure(f"No data for {title}")
    fig = px.bar(
        table,
        x=value_col,
        y=label_col,
        orientation="h",
        title=title,
        template=DARK_TEMPLATE,
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(autorange="reversed"),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def time_series_line(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: str | None,
    title: str,
) -> go.Figure:
    """Time-series line chart with optional grouping by ``color_col``."""

    if df is None or df.empty or x_col not in df.columns or y_col not in df.columns:
        return _empty_figure(f"No data for {title}")
    table = df.copy()
    table[y_col] = pd.to_numeric(table[y_col], errors="coerce")
    table = table.dropna(subset=[x_col, y_col])
    if table.empty:
        return _empty_figure(f"No data for {title}")
    kwargs = {"x": x_col, "y": y_col, "title": title, "template": DARK_TEMPLATE}
    if color_col and color_col in table.columns:
        kwargs["color"] = color_col
    fig = px.line(table, **kwargs)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def grouped_bar(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: str | None,
    title: str,
) -> go.Figure:
    """Grouped bar chart, e.g. cluster rollups."""

    if df is None or df.empty or x_col not in df.columns or y_col not in df.columns:
        return _empty_figure(f"No data for {title}")
    table = df.copy()
    table[y_col] = pd.to_numeric(table[y_col], errors="coerce")
    table = table.dropna(subset=[y_col])
    if table.empty:
        return _empty_figure(f"No data for {title}")
    kwargs = {"x": x_col, "y": y_col, "title": title, "template": DARK_TEMPLATE, "barmode": "group"}
    if color_col and color_col in table.columns:
        kwargs["color"] = color_col
    fig = px.bar(table, **kwargs)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig
