"""KPI tiles and severity badges."""

from __future__ import annotations

from typing import Any

from dash import html

from services.normalizers import LEVEL_COLORS, normalize_severity

SEVERITY_CLASS = {
    "CRITICAL": "kpi-critical",
    "WARNING": "kpi-warning",
    "INFO": "kpi-info",
    "OK": "kpi-ok",
}


def kpi_card(label: str, value: Any, severity: str = "INFO", hint: str | None = None) -> html.Div:
    """Render a single KPI tile with optional severity styling."""

    level = normalize_severity(severity)
    children = [
        html.Div(label, className="kpi-label"),
        html.Div(str(value), className="kpi-value"),
    ]
    if hint:
        children.append(html.Div(hint, className="kpi-hint"))
    return html.Div(children, className=f"kpi-card {SEVERITY_CLASS.get(level, 'kpi-info')}")


def kpi_row(cards: list[html.Div]) -> html.Div:
    """Render a horizontal row of KPI cards."""

    return html.Div(cards, className="kpi-row")


def severity_badge(level: str) -> html.Span:
    """Inline severity badge for table cells or headers."""

    normalized = normalize_severity(level)
    return html.Span(
        normalized,
        className=f"severity-badge severity-{normalized.lower()}",
        style={"--badge-color": LEVEL_COLORS.get(normalized, "#64748b")},
    )


def empty_state(title: str, suggested_command: str | None = None) -> html.Div:
    """Render an empty-state panel when collector output is missing."""

    children: list[Any] = [
        html.Div("No data available", className="empty-state-eyebrow"),
        html.Div(title, className="empty-state-title"),
    ]
    if suggested_command:
        children.append(
            html.Div(
                [
                    html.Div("Run the collector to populate this view:", className="empty-state-hint"),
                    html.Code(suggested_command, className="empty-state-command"),
                ],
                className="empty-state-suggest",
            )
        )
    return html.Div(children, className="empty-state")


def section_panel(title: str, children: Any, subtitle: str | None = None) -> html.Div:
    """Render a titled chart/table panel container."""

    header_children: list[Any] = [html.Div(title, className="panel-title")]
    if subtitle:
        header_children.append(html.Div(subtitle, className="panel-subtitle"))
    return html.Div(
        [
            html.Div(header_children, className="panel-header"),
            html.Div(children, className="panel-body"),
        ],
        className="panel",
    )
