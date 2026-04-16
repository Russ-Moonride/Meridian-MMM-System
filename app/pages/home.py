"""
app/pages/home.py
~~~~~~~~~~~~~~~~~
Client list page — shows all configured clients with their run status.
Clicking "View Results" updates the client store and navigates to /results.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import dash
from dash import Input, Output, callback, html
import dash_bootstrap_components as dbc

import data as app_data

dash.register_page(__name__, path="/", title="Clients — MMM Workbench")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status_badge(status: dict) -> dbc.Badge:
    s = status.get("status", "no_run")
    if s == "complete":
        return dbc.Badge("✓ Run complete", color="success", className="status-badge")
    if s == "failed":
        return dbc.Badge("✗ Run failed", color="danger", className="status-badge")
    return dbc.Badge("○ No run yet", color="secondary", className="status-badge")


def _run_meta(status: dict) -> str:
    if status.get("status") == "complete":
        ts = status.get("completed_at", "")[:10]
        model_type = status.get("model_type", "")
        return f"{ts}  ·  {model_type} run"
    return "Model has not been run for this client."


def _client_card(client: dict) -> dbc.Card:
    cid = client["client_id"]
    cfg = client["config"]
    status = client["status"]

    kpi_label = cfg.get("kpi_column", "KPI")
    kpi_type = cfg.get("kpi_type", "")
    n_paid = len(cfg.get("channels", []))
    n_organic = len(cfg.get("organic_channels", []))
    n_channels = n_paid + n_organic

    geos = status.get("n_geos", "—")
    weeks = status.get("n_weeks", "—")

    display_name = cid.replace("_", " ").title()

    return dbc.Card(
        [
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.H5(display_name, className="mb-1 fw-bold"),
                            _status_badge(status),
                        ],
                        className="d-flex justify-content-between align-items-start mb-2",
                    ),
                    html.P(
                        _run_meta(status),
                        className="text-muted small mb-3",
                    ),
                    html.Hr(className="my-2"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Div("KPI", className="kpi-label"),
                                    html.Div(f"{kpi_label}", className="fw-semibold"),
                                ],
                                width=4,
                            ),
                            dbc.Col(
                                [
                                    html.Div("Channels", className="kpi-label"),
                                    html.Div(
                                        f"{n_paid} paid"
                                        + (f" + {n_organic} organic" if n_organic else ""),
                                        className="fw-semibold",
                                    ),
                                ],
                                width=5,
                            ),
                            dbc.Col(
                                [
                                    html.Div("Geos", className="kpi-label"),
                                    html.Div(str(geos), className="fw-semibold"),
                                ],
                                width=3,
                            ),
                        ],
                        className="mb-3",
                    ),
                    html.Div(
                        [
                            dbc.Button(
                                "View Results →",
                                id={"type": "view-results-btn", "index": cid},
                                color="primary",
                                size="sm",
                                className="me-2",
                                n_clicks=0,
                            ),
                            dbc.Button(
                                "Diagnostics",
                                id={"type": "view-diag-btn", "index": cid},
                                color="outline-secondary",
                                size="sm",
                                n_clicks=0,
                            ),
                        ]
                    ),
                ]
            )
        ],
        className="client-card h-100 shadow-sm",
    )


# ── Layout (function — evaluated on each page load) ───────────────────────────

def layout(**kwargs):
    clients = app_data.list_clients()
    return dbc.Container(
        [
            dbc.Row(
                dbc.Col(
                    html.H4("Configured Clients", className="text-primary fw-bold mb-0"),
                    width=12,
                ),
                className="mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(_client_card(c), width=12, md=6, lg=4, className="mb-4")
                    for c in clients
                ]
            ),
        ],
        fluid=True,
        className="px-4",
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────


@callback(
    Output("client-store", "data", allow_duplicate=True),
    Output("app-url", "pathname"),
    Input({"type": "view-results-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def navigate_to_results(n_clicks_list):
    """Update store and redirect to /results when a card button is clicked."""
    if not any(n for n in n_clicks_list if n):
        return dash.no_update, dash.no_update
    ctx = dash.callback_context
    triggered = ctx.triggered[0]
    btn_id = json.loads(triggered["prop_id"].split(".")[0])
    return btn_id["index"], "/results"


@callback(
    Output("client-store", "data", allow_duplicate=True),
    Output("app-url", "pathname", allow_duplicate=True),
    Input({"type": "view-diag-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def navigate_to_diagnostics(n_clicks_list):
    """Update store and redirect to /diagnostics when a card button is clicked."""
    if not any(n for n in n_clicks_list if n):
        return dash.no_update, dash.no_update
    ctx = dash.callback_context
    triggered = ctx.triggered[0]
    btn_id = json.loads(triggered["prop_id"].split(".")[0])
    return btn_id["index"], "/diagnostics"
