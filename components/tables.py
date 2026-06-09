"""Data table helpers for the Dash dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
from dash import dash_table, dcc, html

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


# ---------------------------------------------------------------------------
# Presentation detail table (progress bars + badges)
# ---------------------------------------------------------------------------


def _progress_bar(value: float | None) -> html.Div:
    """Render a horizontal progress bar with a numeric label."""

    pct: float | None
    try:
        pct = float(value) if value is not None and not pd.isna(value) else None
    except (TypeError, ValueError):
        pct = None
    if pct is None:
        return html.Div("—", className="cell-progress cell-progress-empty")
    clamped = max(0.0, min(100.0, pct))
    tone = "high" if clamped >= 80 else ("mid" if clamped >= 50 else "low")
    return html.Div(
        [
            html.Div(
                html.Div(
                    className=f"progress-fill progress-fill-{tone}",
                    style={"width": f"{clamped:.1f}%"},
                ),
                className="progress-track",
            ),
            html.Span(f"{pct:.1f}%", className=f"progress-label progress-label-{tone}"),
        ],
        className="cell-progress",
    )


def _pill(text: str, kind: str) -> html.Span:
    """Render a colored pill/badge."""

    return html.Span(str(text), className=f"detail-pill detail-pill-{kind}")


def _thp_pill(value: Any) -> html.Span:
    """Render the transparent_hugepages value as a pill, preserving brackets."""

    raw = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    text = raw.strip()
    if not text:
        return html.Span("—", className="detail-pill detail-pill-muted")
    # Tone: anything other than 'never' selected is treated as risky (red).
    selected = text
    if "[" in text and "]" in text:
        try:
            selected = text[text.index("[") + 1 : text.index("]")].strip()
        except ValueError:
            selected = text
    tone = "ok" if selected.lower() == "never" else "danger"
    return html.Span(text, className=f"detail-pill detail-pill-{tone}")


def _format_number(value: Any, decimals: int = 0) -> str:
    """Format a numeric cell, returning em-dash if missing."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(number):
        return "—"
    if decimals == 0:
        return f"{int(round(number)):,}"
    return f"{number:,.{decimals}f}"


def _render_cell(row: dict, column: dict) -> Any:
    column_id = column["id"]
    renderer = column.get("type", "text")
    value = row.get(column_id)
    if renderer == "progress":
        return _progress_bar(value)
    if renderer == "type_badge":
        if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
            return html.Span("—", className="detail-pill detail-pill-muted")
        return _pill(str(value).upper(), "danger")
    if renderer == "state_badge":
        if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
            return html.Span("—", className="detail-pill detail-pill-muted")
        tone = "ok" if str(value).strip().upper() == "MOUNTED" else "muted"
        return _pill(str(value).upper(), tone)
    if renderer == "thp":
        return _thp_pill(value)
    if renderer == "number":
        decimals = int(column.get("decimals", 0))
        return _format_number(value, decimals)
    if renderer == "strong":
        text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
        return html.Span(text or "—", className="cell-strong")
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    return text or "—"


def detail_table(
    df: pd.DataFrame,
    table_id: str,
    columns: list[dict[str, Any]],
    *,
    empty_message: str = "No rows to display.",
    page_size: int = 25,
    download_stem: str | None = None,
) -> html.Div:
    """Render a custom presentation table with progress bars and badges.

    Each column dict supports: id, name, type (text/strong/number/progress/
    type_badge/state_badge/thp), decimals (for number).
    """

    rows = df.to_dict("records") if df is not None and not df.empty else []
    header = html.Thead(
        html.Tr([html.Th(column["name"], className="detail-th") for column in columns])
    )
    if not rows:
        body = html.Tbody(
            [
                html.Tr(
                    [html.Td(empty_message, colSpan=len(columns), className="detail-empty")]
                )
            ]
        )
    else:
        body = html.Tbody(
            [
                html.Tr(
                    [html.Td(_render_cell(row, column), className="detail-td") for column in columns],
                    className="detail-tr",
                )
                for row in rows[:page_size]
            ]
        )

    toolbar_children: list[Any] = [
        html.Button("Columns", id=f"{table_id}-cols", className="detail-toolbar-btn"),
    ]
    download_children: list[Any] = []
    if download_stem:
        toolbar_children.extend(
            [
                html.Button(
                    [html.Span("↓ ", className="detail-toolbar-icon"), "CSV"],
                    id=f"{table_id}-csv-btn",
                    className="detail-toolbar-btn",
                ),
                html.Button(
                    [html.Span("↓ ", className="detail-toolbar-icon"), "JSON"],
                    id=f"{table_id}-json-btn",
                    className="detail-toolbar-btn",
                ),
            ]
        )
        download_children = [
            dcc.Download(id=f"{table_id}-csv-download"),
            dcc.Download(id=f"{table_id}-json-download"),
        ]
    toolbar = html.Div(toolbar_children, className="detail-toolbar")

    shown = min(len(rows), page_size)
    footer = html.Div(
        [
            html.Span(
                [
                    "Showing ",
                    html.Strong(str(shown)),
                    " of ",
                    html.Strong(str(len(rows))),
                    " rows",
                ],
                className="detail-footer-count",
            ),
            html.Div(
                [
                    html.Button("‹", className="detail-page-btn", disabled=True),
                    html.Span("1", className="detail-page-current"),
                    html.Button("›", className="detail-page-btn", disabled=True),
                    html.Span(f"{page_size}/page", className="detail-page-size"),
                ],
                className="detail-footer-pager",
            ),
        ],
        className="detail-footer",
    )

    return html.Div(
        [
            toolbar,
            html.Div(
                html.Table([header, body], className="detail-table"),
                className="detail-table-scroll",
            ),
            footer,
            *download_children,
        ],
        className="detail-table-container",
    )


