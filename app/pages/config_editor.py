"""
app/pages/config_editor.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Config editor — view and edit the YAML config for the selected client.
Writes changes back to configs/{client_id}.yaml on save.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import dash
from dash import Input, Output, State, callback, dcc, html
import dash_bootstrap_components as dbc
import yaml

import data as app_data

dash.register_page(__name__, path="/config", title="Config — MMM Workbench")

# ── Layout ────────────────────────────────────────────────────────────────────

layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    html.H4(id="config-title", className="text-primary fw-bold mb-0"),
                    width="auto",
                ),
                dbc.Col(
                    dbc.Badge(
                        "configs/{client_id}.yaml",
                        id="config-filepath-badge",
                        color="light",
                        text_color="muted",
                        className="small align-self-center ms-1",
                    ),
                    width="auto",
                    className="d-flex align-items-center",
                ),
            ],
            align="center",
            className="mb-3",
        ),
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            dcc.Textarea(
                                id="config-textarea",
                                value="",
                                style={
                                    "width": "100%",
                                    "height": "620px",
                                    "fontFamily": (
                                        '"SFMono-Regular", Consolas, '
                                        '"Liberation Mono", Menlo, monospace'
                                    ),
                                    "fontSize": "13px",
                                    "lineHeight": "1.55",
                                    "border": "1px solid #dee2e6",
                                    "borderRadius": "6px",
                                    "padding": "12px 14px",
                                    "resize": "vertical",
                                    "backgroundColor": "#FAFAFA",
                                },
                                spellCheck=False,
                            ),
                            html.Div(
                                [
                                    dbc.Button(
                                        "Save Config",
                                        id="config-save-btn",
                                        color="primary",
                                        size="sm",
                                        className="me-2",
                                        n_clicks=0,
                                    ),
                                    dbc.Button(
                                        "Reset",
                                        id="config-reset-btn",
                                        color="outline-secondary",
                                        size="sm",
                                        n_clicks=0,
                                    ),
                                    html.Div(
                                        id="config-save-status",
                                        className="d-inline-block ms-3",
                                    ),
                                ],
                                className="mt-3 d-flex align-items-center",
                            ),
                        ]
                    ),
                    className="shadow-sm border-0",
                ),
                width=12,
                xl=10,
            )
        ),
        dbc.Row(
            dbc.Col(
                dbc.Alert(
                    [
                        html.Strong("Note: "),
                        "Changes saved here update the config file on disk immediately. "
                        "They take effect on the next model run — they do not reprocess "
                        "existing outputs.",
                    ],
                    color="warning",
                    className="mt-3 py-2 small",
                ),
                width=12,
                xl=10,
            )
        ),
    ],
    fluid=True,
    className="px-4",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


@callback(
    Output("config-title", "children"),
    Output("config-filepath-badge", "children"),
    Output("config-textarea", "value"),
    Input("client-store", "data"),
    Input("config-reset-btn", "n_clicks"),
)
def load_config_text(client_id: str | None, _reset_clicks):
    """Load the YAML for the selected client into the textarea."""
    if not client_id:
        return "Config Editor", "", "# Select a client to view its config."
    try:
        raw = app_data.get_config_raw(client_id)
        display_name = client_id.replace("_", " ").title()
        # Derive the yaml filename from the config path
        configs = app_data._all_configs()
        _, yaml_path = configs[client_id]
        badge = f"configs/{yaml_path.name}"
        return f"{display_name} — Config", badge, raw
    except Exception as e:
        return "Config Editor", "", f"# Error loading config:\n# {e}"


@callback(
    Output("config-save-status", "children"),
    Input("config-save-btn", "n_clicks"),
    State("config-textarea", "value"),
    State("client-store", "data"),
    prevent_initial_call=True,
)
def save_config(n_clicks: int, yaml_text: str, client_id: str | None):
    """Validate YAML syntax and write to disk."""
    if not client_id or not yaml_text:
        return dbc.Badge("Nothing to save", color="secondary")
    try:
        yaml.safe_load(yaml_text)           # validate syntax before writing
        app_data.save_config(client_id, yaml_text)
        return dbc.Badge("✓ Saved", color="success", className="px-2 py-1")
    except yaml.YAMLError as e:
        return dbc.Badge(
            f"✗ YAML error: {e}",
            color="danger",
            className="px-2 py-1",
            style={"maxWidth": "400px", "whiteSpace": "normal"},
        )
    except Exception as e:
        return dbc.Badge(f"✗ {e}", color="danger", className="px-2 py-1")
