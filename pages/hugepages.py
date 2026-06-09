"""HugePages Analytics page."""

from __future__ import annotations

import dash
import pandas as pd
import plotly.express as px
from dash import callback, dash_table, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, kpi_card, kpi_row, section_panel
from components.charts import horizontal_top_bar
from components.filters import apply_cluster_filter
from services.data_loader import read_output
from services.normalizers import normalize_hugepages

dash.register_page(__name__, path="/os/hugepages", name="HugePages Analytics")


PAGE_TITLE = "HugePages Analytics"
PAGE_SUBTITLE = (
    "HugePages allocation, utilization, free page risk, "
    "and Transparent HugePages compliance."
)

NODE_DETAIL_COLUMNS = [
    {"id": "cluster", "name": "CLUSTER"},
    {"id": "host", "name": "HOST"},
    {"id": "mem_gb_fmt", "name": "MEM GB"},
    {"id": "hp_total_gb_fmt", "name": "HP TOTAL GB"},
    {"id": "hp_used_gb_fmt", "name": "HP USED GB"},
    {"id": "hp_free_gb_fmt", "name": "HP FREE GB"},
    {"id": "hp_used_pct_fmt", "name": "HP USED %"},
    {"id": "hp_alloc_pct_ram_fmt", "name": "HP ALLOC % RAM"},
    {"id": "thp_status", "name": "THP"},
    {"id": "timestamp", "name": "TIMESTAMP"},
]

NUMERIC_COLUMN_IDS = {
    "mem_gb_fmt",
    "hp_total_gb_fmt",
    "hp_used_gb_fmt",
    "hp_free_gb_fmt",
    "hp_used_pct_fmt",
    "hp_alloc_pct_ram_fmt",
}


def _fmt_int(value, *, comma: bool = False) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return "—"
    return f"{number:,}" if comma else str(number)


def _fmt_pct(value, decimals: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:.{decimals}f}%"


def _prepare_detail_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Add display-formatted columns to the detail dataframe."""

    table = df.copy()
    table["mem_gb_fmt"] = table["mem_gb"].map(lambda v: _fmt_int(v, comma=True))
    table["hp_total_gb_fmt"] = table["hp_total_gb"].map(lambda v: _fmt_int(v, comma=True))
    table["hp_used_gb_fmt"] = table["hp_used_gb"].map(lambda v: _fmt_int(v, comma=True))
    table["hp_free_gb_fmt"] = table["hp_free_gb"].map(lambda v: _fmt_int(v, comma=True))
    table["hp_used_pct_fmt"] = table["hp_used_pct"].map(lambda v: _fmt_pct(v, 1))
    table["hp_alloc_pct_ram_fmt"] = table["hp_alloc_pct_ram"].map(lambda v: _fmt_pct(v, 1))
    table["thp_status"] = table["thp_status"].fillna("").astype(str)
    table["timestamp"] = table["timestamp"].fillna("").astype(str)
    return table


def _conditional_styles() -> list[dict]:
    styles: list[dict] = []
    # Right-align numeric columns
    for column_id in NUMERIC_COLUMN_IDS:
        styles.append(
            {
                "if": {"column_id": column_id},
                "textAlign": "right",
            }
        )
    # HP USED % thresholds
    styles.extend(
        [
            {
                "if": {
                    "filter_query": "{hp_used_pct} < 80",
                    "column_id": "hp_used_pct_fmt",
                },
                "color": "#16a34a",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": "{hp_used_pct} >= 80 && {hp_used_pct} < 95",
                    "column_id": "hp_used_pct_fmt",
                },
                "color": "#f59e0b",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": "{hp_used_pct} >= 95",
                    "column_id": "hp_used_pct_fmt",
                },
                "color": "#ef4444",
                "fontWeight": "700",
            },
        ]
    )
    # HP ALLOC % RAM thresholds
    styles.extend(
        [
            {
                "if": {
                    "filter_query": "{hp_alloc_pct_ram} >= 40 && {hp_alloc_pct_ram} <= 80",
                    "column_id": "hp_alloc_pct_ram_fmt",
                },
                "color": "#16a34a",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": "{hp_alloc_pct_ram} < 40",
                    "column_id": "hp_alloc_pct_ram_fmt",
                },
                "color": "#f59e0b",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": "{hp_alloc_pct_ram} > 80",
                    "column_id": "hp_alloc_pct_ram_fmt",
                },
                "color": "#f59e0b",
                "fontWeight": "600",
            },
        ]
    )
    # THP mode coloring
    styles.extend(
        [
            {
                "if": {
                    "filter_query": '{thp_mode} = "never"',
                    "column_id": "thp_status",
                },
                "color": "#16a34a",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": '{thp_mode} = "madvise"',
                    "column_id": "thp_status",
                },
                "color": "#f59e0b",
                "fontWeight": "600",
            },
            {
                "if": {
                    "filter_query": '{thp_mode} = "always"',
                    "column_id": "thp_status",
                },
                "color": "#ef4444",
                "fontWeight": "700",
            },
            {
                "if": {
                    "filter_query": '{thp_mode} = "unknown"',
                    "column_id": "thp_status",
                },
                "color": "#94a3b8",
            },
        ]
    )
    return styles


def _node_detail_table(df: pd.DataFrame, table_id: str) -> dash_table.DataTable:
    rendered = _prepare_detail_rows(df)
    data_columns = [
        "hp_used_pct",
        "hp_alloc_pct_ram",
        "thp_mode",
        *(col["id"] for col in NODE_DETAIL_COLUMNS),
    ]
    data = rendered[data_columns].to_dict("records")
    return dash_table.DataTable(
        id=table_id,
        columns=NODE_DETAIL_COLUMNS,
        data=data,
        sort_action="native",
        page_size=25,
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#1e293b",
            "color": "#e2e8f0",
            "fontWeight": "700",
            "textTransform": "uppercase",
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
        style_data_conditional=_conditional_styles(),
    )


def _thp_mode_chart(df: pd.DataFrame) -> dcc.Graph:
    if df.empty or "thp_mode" not in df.columns:
        counts = pd.DataFrame({"thp_mode": [], "count": []})
    else:
        counts = df["thp_mode"].fillna("unknown").value_counts().reset_index()
        counts.columns = ["thp_mode", "count"]
    fig = px.bar(
        counts,
        x="thp_mode",
        y="count",
        title="THP mode count",
        template="plotly_dark",
        color="thp_mode",
        color_discrete_map={
            "never": "#16a34a",
            "madvise": "#f59e0b",
            "always": "#ef4444",
            "unknown": "#94a3b8",
        },
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
    )
    return dcc.Graph(figure=fig)


def _hp_used_vs_total_chart(df: pd.DataFrame) -> dcc.Graph:
    if df.empty:
        return dcc.Graph(figure=grouped_bar(df, "host", "hp_total_gb", None, "HP Used GB vs HP Total GB"))
    long = df[["host", "hp_total_gb", "hp_used_gb"]].melt(
        id_vars="host",
        value_vars=["hp_total_gb", "hp_used_gb"],
        var_name="metric",
        value_name="gb",
    )
    long["metric"] = long["metric"].map(
        {"hp_total_gb": "HP Total GB", "hp_used_gb": "HP Used GB"}
    )
    fig = px.bar(
        long,
        x="host",
        y="gb",
        color="metric",
        barmode="group",
        template="plotly_dark",
        title="HP Used GB vs HP Total GB by Host",
        color_discrete_map={"HP Total GB": "#2563eb", "HP Used GB": "#22c55e"},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(tickangle=-30),
    )
    return dcc.Graph(figure=fig)


def _filters_panel(df: pd.DataFrame) -> html.Div:
    clusters = sorted(df["cluster"].dropna().astype(str).unique().tolist())
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Cluster", className="topbar-filter-label"),
                    dcc.Dropdown(
                        id="hugepages-cluster-filter",
                        options=[{"label": c, "value": c} for c in clusters],
                        value=[],
                        multi=True,
                        placeholder="All clusters",
                    ),
                ],
                className="hugepages-filter-item",
            ),
            html.Div(
                [
                    html.Label("Host search", className="topbar-filter-label"),
                    dcc.Input(
                        id="hugepages-host-search",
                        type="text",
                        placeholder="filter by host…",
                        debounce=True,
                        className="hugepages-host-input",
                    ),
                ],
                className="hugepages-filter-item",
            ),
            html.Div(
                [
                    html.Label("THP mode", className="topbar-filter-label"),
                    dcc.Dropdown(
                        id="hugepages-thp-filter",
                        options=[
                            {"label": "All", "value": "all"},
                            {"label": "never", "value": "never"},
                            {"label": "madvise", "value": "madvise"},
                            {"label": "always", "value": "always"},
                            {"label": "unknown", "value": "unknown"},
                        ],
                        value="all",
                        clearable=False,
                    ),
                ],
                className="hugepages-filter-item",
            ),
            html.Div(
                [
                    html.Label("Severity", className="topbar-filter-label"),
                    dcc.Dropdown(
                        id="hugepages-severity-filter",
                        options=[
                            {"label": "All", "value": "all"},
                            {"label": "OK", "value": "OK"},
                            {"label": "INFO", "value": "INFO"},
                            {"label": "WARNING", "value": "WARNING"},
                            {"label": "CRITICAL", "value": "CRITICAL"},
                        ],
                        value="all",
                        clearable=False,
                    ),
                ],
                className="hugepages-filter-item",
            ),
        ],
        className="hugepages-filter-row",
    )


def _is_risky(row: dict) -> bool:
    severity = str(row.get("severity") or "OK").upper()
    if severity in {"WARNING", "CRITICAL"}:
        return True
    mode = str(row.get("thp_mode") or "unknown")
    if mode != "never":
        return True
    used_pct = row.get("hp_used_pct")
    try:
        if used_pct is not None and not pd.isna(used_pct) and float(used_pct) >= 80:
            return True
    except (TypeError, ValueError):
        pass
    alloc = row.get("hp_alloc_pct_ram")
    try:
        if alloc is not None and not pd.isna(alloc):
            value = float(alloc)
            if value < 40 or value > 80:
                return True
    except (TypeError, ValueError):
        pass
    return False


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

    header = html.Div(
        [
            html.H2(PAGE_TITLE, className="hugepages-title"),
            html.Div(PAGE_SUBTITLE, className="hugepages-subtitle"),
        ],
        className="hugepages-header",
    )

    clusters = df["cluster"].dropna().astype(str).unique()
    hosts = df["host"].dropna().astype(str).unique()
    total_ram_tb = pd.to_numeric(df["mem_gb"], errors="coerce").sum(skipna=True) / 1024
    hp_total_gb = pd.to_numeric(df["hp_total_gb"], errors="coerce").sum(skipna=True)
    hp_used_gb = pd.to_numeric(df["hp_used_gb"], errors="coerce").sum(skipna=True)
    hp_free_gb = pd.to_numeric(df["hp_free_gb"], errors="coerce").sum(skipna=True)
    avg_used_pct = pd.to_numeric(df["hp_used_pct"], errors="coerce").mean(skipna=True)
    thp_not_never = int((df["thp_mode"] != "never").sum())

    cards = kpi_row(
        [
            kpi_card("Clusters", len(clusters), "INFO"),
            kpi_card("Hosts", len(hosts), "INFO"),
            kpi_card(
                "Total RAM TB",
                f"{total_ram_tb:,.1f}" if not pd.isna(total_ram_tb) else "—",
                "INFO",
            ),
            kpi_card(
                "HP Total GB",
                f"{hp_total_gb:,.0f}" if not pd.isna(hp_total_gb) else "—",
                "INFO",
            ),
            kpi_card(
                "HP Used GB",
                f"{hp_used_gb:,.0f}" if not pd.isna(hp_used_gb) else "—",
                "INFO",
            ),
            kpi_card(
                "HP Free GB",
                f"{hp_free_gb:,.0f}" if not pd.isna(hp_free_gb) else "—",
                "INFO",
            ),
            kpi_card(
                "Avg HP Used %",
                f"{avg_used_pct:.1f}%" if not pd.isna(avg_used_pct) else "—",
                "INFO",
            ),
            kpi_card(
                "THP Not Never",
                thp_not_never,
                "WARNING" if thp_not_never else "OK",
            ),
        ]
    )

    chart_used_pct = section_panel(
        "HP Used % by Host",
        dcc.Graph(
            figure=horizontal_top_bar(
                df, "hp_used_pct", "host", "HP Used % by Host"
            )
        ),
    )
    chart_alloc_pct = section_panel(
        "HP Alloc % RAM by Host",
        dcc.Graph(
            figure=horizontal_top_bar(
                df, "hp_alloc_pct_ram", "host", "HP Alloc % RAM by Host"
            )
        ),
    )
    chart_used_vs_total = section_panel(
        "HP Used GB vs HP Total GB by Host",
        _hp_used_vs_total_chart(df),
    )
    chart_thp = section_panel("THP mode count", _thp_mode_chart(df))

    charts_grid = html.Div(
        [chart_used_pct, chart_alloc_pct, chart_used_vs_total, chart_thp],
        className="panel-grid",
    )

    node_detail_panel = section_panel(
        "HUGEPAGES — NODE DETAIL",
        _node_detail_table(df, "hugepages-node-detail"),
    )

    risk_df = df[df.apply(_is_risky, axis=1)] if not df.empty else df
    if risk_df.empty:
        risk_panel = section_panel(
            "Risk table",
            html.Div("No risky hosts.", className="kpi-hint"),
        )
    else:
        risk_panel = section_panel(
            "Risk table",
            _node_detail_table(risk_df, "hugepages-risk-table"),
        )

    return html.Div([header, cards, charts_grid, node_detail_panel, risk_panel])
