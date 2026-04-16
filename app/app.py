"""
app/app.py
~~~~~~~~~~
Dash multi-page app for the MMM workbench.

Usage (from repo root):
    python app/app.py          # development server on :8050
    dash run app/app.py        # via Dash CLI
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make app/ and repo root importable regardless of working directory
_APP_DIR = Path(__file__).parent
_ROOT = _APP_DIR.parent
sys.path.insert(0, str(_APP_DIR))
sys.path.insert(0, str(_ROOT))

import dash
from dash import Dash, Input, Output, State, dcc, html
import dash_bootstrap_components as dbc

import data as app_data

app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.FLATLY],
    suppress_callback_exceptions=True,
    title="MMM Workbench",
)
server = app.server   # expose Flask server for `dash run`

# ── Navbar ────────────────────────────────────────────────────────────────────

def _nav_link(label: str, href: str) -> dbc.NavItem:
    return dbc.NavItem(
        dbc.NavLink(label, href=href, active="partial", className="fw-medium")
    )


navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.NavbarBrand(
                [html.Span("MMM", className="fw-bold"), " Workbench"],
                href="/",
                className="me-4",
            ),
            dbc.Nav(
                [
                    _nav_link("Clients", "/"),
                    _nav_link("Results", "/results"),
                    _nav_link("Diagnostics", "/diagnostics"),
                    _nav_link("Config", "/config"),
                ],
                navbar=True,
                className="me-auto",
            ),
            html.Div(
                [
                    html.Span("Client", className="text-white-50 small me-2"),
                    dcc.Dropdown(
                        id="client-selector",
                        options=[],
                        value=None,
                        clearable=False,
                        style={"width": "190px", "fontSize": "14px"},
                    ),
                ],
                className="d-flex align-items-center",
            ),
        ],
        fluid=True,
    ),
    color="primary",
    dark=True,
    sticky="top",
    className="mb-0 shadow-sm",
)

# ── App layout ────────────────────────────────────────────────────────────────

app.layout = html.Div(
    [
        # Persistent client selection
        dcc.Store(id="client-store", storage_type="session", data="northspore"),
        # Used for programmatic navigation (e.g. clicking a client card)
        dcc.Location(id="app-url", refresh=False),
        navbar,
        html.Div(
            dash.page_container,
            className="py-3",
            style={"minHeight": "calc(100vh - 58px)", "backgroundColor": "#F8F9FA"},
        ),
    ]
)

# ── Callbacks ─────────────────────────────────────────────────────────────────


@app.callback(
    Output("client-selector", "options"),
    Output("client-selector", "value"),
    Input("client-store", "data"),
)
def populate_client_dropdown(stored: str | None):
    """Populate the navbar dropdown from all configured clients."""
    clients = app_data.list_clients()
    options = [
        {
            "label": c["client_id"].replace("_", " ").title(),
            "value": c["client_id"],
        }
        for c in clients
    ]
    value = stored if stored else (options[0]["value"] if options else None)
    return options, value


@app.callback(
    Output("client-store", "data"),
    Input("client-selector", "value"),
    State("client-store", "data"),
    prevent_initial_call=True,
)
def sync_store_from_navbar(selected: str | None, current: str | None) -> str | None:
    """Keep the store in sync when the user picks a client in the navbar."""
    return selected or current


if __name__ == "__main__":
    app.run(debug=True, port=8050)
