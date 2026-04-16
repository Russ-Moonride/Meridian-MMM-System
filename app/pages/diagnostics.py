"""
app/pages/diagnostics.py
~~~~~~~~~~~~~~~~~~~~~~~~
Diagnostics view — R-hat convergence, ESS, and run metadata.
Reads from outputs/{client_id}/diagnostics.json.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import dash
from dash import Input, Output, callback, dash_table, html
import dash_bootstrap_components as dbc

import data as app_data

dash.register_page(__name__, path="/diagnostics", title="Diagnostics — MMM Workbench")

# ── Layout ────────────────────────────────────────────────────────────────────

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H4(id="diag-title", className="text-primary fw-bold mb-0"),
                width=12,
            ),
            className="mb-3",
        ),
        # Summary metric cards
        dbc.Row(id="diag-summary-cards", className="mb-4 g-3"),
        # R-hat and ESS tables side by side
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H6("R-hat by Channel", className="text-muted fw-semibold mb-2"),
                        html.Div(id="rhat-table"),
                    ],
                    width=12,
                    lg=6,
                    className="mb-4",
                ),
                dbc.Col(
                    [
                        html.H6("ESS by Channel", className="text-muted fw-semibold mb-2"),
                        html.Div(id="ess-table"),
                    ],
                    width=12,
                    lg=6,
                    className="mb-4",
                ),
            ]
        ),
    ],
    fluid=True,
    className="px-4",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


@callback(
    Output("diag-title", "children"),
    Output("diag-summary-cards", "children"),
    Output("rhat-table", "children"),
    Output("ess-table", "children"),
    Input("client-store", "data"),
)
def update_diagnostics(client_id: str | None):
    title_base = (client_id or "").replace("_", " ").title()
    title = f"{title_base} — Diagnostics"

    if not client_id:
        return title, [], _no_data_alert(), _no_data_alert()

    diag = app_data.get_diagnostics(client_id)
    if diag is None:
        msg = dbc.Alert(
            [
                html.Strong("No diagnostics found. "),
                "Run the Meridian notebook to generate model output.",
            ],
            color="info",
        )
        return title, [], msg, msg

    rhat_max = diag.get("rhat_max", float("nan"))
    ess_min = diag.get("ess_min", 0)
    converged = diag.get("converged", False)
    runtime = diag.get("runtime_minutes", 0)
    n_chains = diag.get("n_chains", "—")
    n_keep = diag.get("n_keep", "—")
    model_type = diag.get("model_type", "")
    completed = diag.get("completed_at", "")[:10]

    # ── Summary cards ──────────────────────────────────────────────────────
    converged_card = _summary_card(
        "Convergence",
        "✓ Passed" if converged else "✗ Failed",
        "success" if converged else "danger",
    )
    rhat_card = _summary_card(
        "Max R-hat",
        f"{rhat_max:.3f}",
        "success" if rhat_max < 1.05 else "warning" if rhat_max < 1.1 else "danger",
    )
    ess_card = _summary_card(
        "Min ESS",
        str(ess_min),
        "success" if ess_min >= 200 else "warning" if ess_min >= 100 else "danger",
    )
    runtime_card = _summary_card(
        "Runtime",
        f"{runtime:.1f} min",
        "secondary",
    )
    run_card = _summary_card(
        "Run",
        f"{model_type}  ·  {completed}",
        "secondary",
    )
    chains_card = _summary_card(
        "Chains / Samples",
        f"{n_chains} chains × {n_keep} keep",
        "secondary",
    )

    cards = [converged_card, rhat_card, ess_card, runtime_card, run_card, chains_card]

    # ── R-hat table ────────────────────────────────────────────────────────
    rhat_by_ch = diag.get("rhat_by_channel", {})
    rhat_rows = [
        {
            "Channel": ch,
            "R-hat": f"{v:.3f}",
            "Status": "✓ Good" if v < 1.05 else "⚠ Acceptable" if v < 1.1 else "✗ High",
            "_rhat_val": v,
        }
        for ch, v in sorted(rhat_by_ch.items(), key=lambda x: -x[1])
    ]

    rhat_tbl = dash_table.DataTable(
        data=[{k: v for k, v in r.items() if not k.startswith("_")} for r in rhat_rows],
        columns=[
            {"name": "Channel", "id": "Channel"},
            {"name": "R-hat", "id": "R-hat"},
            {"name": "Status", "id": "Status"},
        ],
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#F8F9FA",
            "fontWeight": "600",
            "fontSize": "12px",
            "borderBottom": "2px solid #dee2e6",
            "padding": "8px 12px",
        },
        style_cell={
            "padding": "8px 12px",
            "fontSize": "13px",
            "border": "none",
            "borderBottom": "1px solid #f0f0f0",
        },
        style_data_conditional=[
            {
                "if": {
                    "filter_query": f'{{R-hat}} = "{r["R-hat"]}"' if r["_rhat_val"] >= 1.1 else "",
                    "column_id": "Status",
                },
                "color": "#dc3545",
                "fontWeight": "600",
            }
            for r in rhat_rows
        ]
        + [
            {
                "if": {"filter_query": '{Status} = "⚠ Acceptable"', "column_id": "Status"},
                "color": "#fd7e14",
            },
            {
                "if": {"filter_query": '{Status} = "✓ Good"', "column_id": "Status"},
                "color": "#198754",
            },
            {
                "if": {"filter_query": '{Status} = "✗ High"', "column_id": "Status"},
                "color": "#dc3545",
                "fontWeight": "600",
            },
            {"if": {"row_index": "odd"}, "backgroundColor": "#FAFAFA"},
        ],
    )

    # ── ESS table ──────────────────────────────────────────────────────────
    ess_by_ch = diag.get("ess_by_channel", {})
    ess_rows = [
        {
            "Channel": ch,
            "ESS": str(v),
            "Status": "✓ Good" if v >= 200 else "⚠ Acceptable" if v >= 100 else "✗ Low",
        }
        for ch, v in sorted(ess_by_ch.items(), key=lambda x: x[1])
    ]

    ess_tbl = dash_table.DataTable(
        data=ess_rows,
        columns=[
            {"name": "Channel", "id": "Channel"},
            {"name": "ESS", "id": "ESS"},
            {"name": "Status", "id": "Status"},
        ],
        style_table={"overflowX": "auto"},
        style_header={
            "backgroundColor": "#F8F9FA",
            "fontWeight": "600",
            "fontSize": "12px",
            "borderBottom": "2px solid #dee2e6",
            "padding": "8px 12px",
        },
        style_cell={
            "padding": "8px 12px",
            "fontSize": "13px",
            "border": "none",
            "borderBottom": "1px solid #f0f0f0",
        },
        style_data_conditional=[
            {
                "if": {"filter_query": '{Status} = "⚠ Acceptable"', "column_id": "Status"},
                "color": "#fd7e14",
            },
            {
                "if": {"filter_query": '{Status} = "✓ Good"', "column_id": "Status"},
                "color": "#198754",
            },
            {
                "if": {"filter_query": '{Status} = "✗ Low"', "column_id": "Status"},
                "color": "#dc3545",
                "fontWeight": "600",
            },
            {"if": {"row_index": "odd"}, "backgroundColor": "#FAFAFA"},
        ],
    )

    return title, cards, rhat_tbl, ess_tbl


# ── Component helpers ─────────────────────────────────────────────────────────


def _summary_card(label: str, value: str, color: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(label, className="kpi-label"),
                    html.Div(value, className=f"kpi-value text-{color}"),
                ]
            ),
            className="shadow-sm border-0",
        ),
        width=6,
        md=4,
        lg=2,
    )


def _no_data_alert() -> dbc.Alert:
    return dbc.Alert("No data available.", color="light", className="text-muted")
