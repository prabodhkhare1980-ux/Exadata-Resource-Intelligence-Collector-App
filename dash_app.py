"""Dash entrypoint for the Exadata Resource Intelligence dashboard.

The Dash app is intentionally read-only. It loads collector output from
``output/`` and never opens SSH connections, never imports collector
runtime code from ``main.py``, and never executes collectors.

Authentication is intentionally **not** implemented in Phase 1.

TODO (future phases):
- Reverse-proxy header auth (e.g. enterprise SSO gateway forwarding REMOTE_USER).
- LDAP / OIDC / SAML integration for direct enterprise login.
- Role-based page access (e.g. operators see all pages, app teams scoped to
  their cluster/db filters).
- SQLite-backed datastore for cached/aggregated views; the current loader
  intentionally reads JSON/CSV only.
"""

from __future__ import annotations

import dash
from dash import Input, Output, dcc, html
from dash.dependencies import State

from components.filters import cluster_options_from_outputs
from components.layout import app_layout, page_title_from_path
from services.data_loader import read_output


def build_global_cluster_options() -> list[dict[str, str]]:
    """Aggregate cluster names across the read-only collector outputs."""

    return cluster_options_from_outputs(
        read_output("asm_diskgroups"),
        read_output("hugepages"),
        read_output("db_resource_details"),
        read_output("db_memory_history_summary"),
        read_output("db_memory_cluster_summary"),
        read_output("db_performance"),
        read_output("os_inventory"),
        read_output("version_inventory"),
        read_output("health_summary"),
    )


def create_app() -> dash.Dash:
    """Construct and configure the Dash app."""

    app = dash.Dash(
        __name__,
        use_pages=True,
        suppress_callback_exceptions=True,
        title="Exadata Resource Intelligence",
        update_title=None,
    )

    app.layout = app_layout(dash.page_container, build_global_cluster_options())

    @app.callback(
        Output("global-filter-state", "data"),
        Input("global-cluster-filter", "value"),
        State("global-filter-state", "data"),
    )
    def sync_global_filter(selected, current):
        current = current or {}
        current["clusters"] = selected or []
        return current

    @app.callback(
        Output("page-title", "children"),
        Input("url", "pathname"),
    )
    def update_page_title(pathname: str | None):
        return page_title_from_path(pathname or "/")

    return app


app = create_app()
server = app.server  # for production WSGI deployment in later phases


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)
