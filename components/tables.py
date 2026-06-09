"""Data table helpers for the Dash dashboard."""

from __future__ import annotations

import pandas as pd
from dash import dash_table

SEVERITY_COLORS = {
    "CRITICAL": "#7f1d1d",
    "WARNING": "#78350f",
    "INFO": "#1e3a8a",
    "OK": "#14532d",
}


def _severity_conditional_styles(columns: list[str]) -> list[dict]:
    """Highlight rows by warning_level / warning_severity columns."""

    column_id = None
    for candidate in ("warning_level", "warning_severity"):
        if candidate in columns:
            column_id = candidate
            break
    if column_id is None:
        return []
    styles = []
    for level, color in SEVERITY_COLORS.items():
        styles.append(
            {
                "if": {"filter_query": f"{{{column_id}}} = '{level}'", "column_id": column_id},
                "backgroundColor": color,
                "color": "#fafafa",
                "fontWeight": "600",
            }
        )
    return styles


def data_table(
    df: pd.DataFrame,
    table_id: str,
    page_size: int = 25,
    export_format: str | None = "csv",
) -> dash_table.DataTable:
    """Build a sortable, filterable DataTable with severity highlighting."""

    if df is None or df.empty:
        columns = [{"name": "No data", "id": "no_data"}]
        data: list[dict] = []
    else:
        columns = [{"name": column, "id": column} for column in df.columns]
        data = df.to_dict("records")
    style_data_conditional = _severity_conditional_styles(
        list(df.columns) if df is not None else []
    )
    return dash_table.DataTable(
        id=table_id,
        columns=columns,
        data=data,
        sort_action="native",
        filter_action="native",
        page_size=page_size,
        export_format=export_format,
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#1e293b",
            "color": "#e2e8f0",
            "fontWeight": "600",
            "border": "1px solid #334155",
        },
        style_cell={
            "backgroundColor": "#0f172a",
            "color": "#e2e8f0",
            "border": "1px solid #1e293b",
            "padding": "8px 12px",
            "fontFamily": "Inter, system-ui, sans-serif",
            "fontSize": "13px",
        },
        style_data_conditional=style_data_conditional,
    )
