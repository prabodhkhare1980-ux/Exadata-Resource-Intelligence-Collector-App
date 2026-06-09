"""Raw Data Explorer page."""

from __future__ import annotations

import dash
from dash import callback, dcc, html
from dash.dependencies import Input, Output

from components.cards import empty_state, section_panel
from components.tables import data_table
from services.data_loader import list_output_files, read_file

dash.register_page(__name__, path="/explore/raw", name="Raw Data Explorer")


def _file_options() -> list[dict[str, str]]:
    return [{"label": path.name, "value": str(path)} for path in list_output_files()]


def layout():
    options = _file_options()
    if not options:
        return empty_state(
            "No JSON or CSV files found under output/",
            "python main.py --config config/your-config.yaml",
        )
    return html.Div(
        [
            section_panel(
                "Select output file",
                dcc.Dropdown(
                    id="raw-file-selector",
                    options=options,
                    value=options[0]["value"],
                    clearable=False,
                    className="topbar-filter",
                ),
            ),
            html.Div(id="raw-file-content"),
        ]
    )


@callback(
    Output("raw-file-content", "children"),
    Input("raw-file-selector", "value"),
)
def render_raw_file(path: str | None):
    if not path:
        return empty_state("Pick a file from the dropdown above")
    from pathlib import Path

    df = read_file(Path(path))
    if df.empty:
        return empty_state("File is empty or could not be parsed", path)
    return section_panel(Path(path).name, data_table(df, "raw-file-table"))
