"""
app/pages/results.py
~~~~~~~~~~~~~~~~~~~~
Results view — ROI by channel, revenue attribution, and weekly contribution
time series. Reads from outputs/{client_id}/contributions.csv.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import dash
from dash import Input, Output, callback, dcc, html
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

import data as app_data

dash.register_page(__name__, path="/results", title="Results — MMM Workbench")

COLORS = app_data.CHANNEL_COLORS

# ── Layout ────────────────────────────────────────────────────────────────────

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                html.H4(id="results-title", className="text-primary fw-bold mb-0"),
                width=12,
            ),
            className="mb-3",
        ),
        # KPI summary cards
        dbc.Row(id="kpi-cards", className="mb-4 g-3"),
        # ROI chart + contribution pie
        dbc.Row(
            [
                dbc.Col(
                    html.Div(dcc.Graph(id="roi-chart"), className="chart-card"),
                    width=12,
                    lg=7,
                    className="mb-4",
                ),
                dbc.Col(
                    html.Div(dcc.Graph(id="contribution-pie"), className="chart-card"),
                    width=12,
                    lg=5,
                    className="mb-4",
                ),
            ]
        ),
        # Weekly time series
        dbc.Row(
            dbc.Col(
                html.Div(dcc.Graph(id="weekly-timeseries"), className="chart-card"),
                width=12,
                className="mb-4",
            )
        ),
    ],
    fluid=True,
    className="px-4",
)


# ── Callbacks ─────────────────────────────────────────────────────────────────


@callback(
    Output("results-title", "children"),
    Output("kpi-cards", "children"),
    Output("roi-chart", "figure"),
    Output("contribution-pie", "figure"),
    Output("weekly-timeseries", "figure"),
    Input("client-store", "data"),
)
def update_results(client_id: str | None):
    if not client_id:
        return "No client selected", [], _placeholder_fig(), _placeholder_fig(), _placeholder_fig()

    try:
        cfg = app_data.get_config(client_id)
    except KeyError:
        return f"Unknown client: {client_id}", [], _placeholder_fig(), _placeholder_fig(), _placeholder_fig()

    kpi_col = cfg.get("kpi_column", "KPI")
    kpi_type = cfg.get("kpi_type", "revenue")
    channels = cfg.get("channels", [])
    organic_chs = cfg.get("organic_channels", [])
    title = client_id.replace("_", " ").title() + " — Results"

    contributions = app_data.get_contributions(client_id)
    if contributions is None:
        no_data = dbc.Col(
            dbc.Alert(
                [
                    html.Strong("No model output found. "),
                    "Run the Meridian notebook to generate results.",
                ],
                color="info",
            ),
            width=12,
        )
        return title, [no_data], _no_data_fig(), _no_data_fig(), _no_data_fig()

    paid = contributions[contributions["channel_type"] == "paid"]
    is_revenue = kpi_type == "revenue"

    # ── KPI summary cards ──────────────────────────────────────────────────
    total_kpi = contributions["contribution"].sum()
    total_spend = paid["spend"].sum()
    roas = total_kpi / total_spend if total_spend > 0 else 0

    fmt_kpi = f"${total_kpi:,.0f}" if is_revenue else f"{total_kpi:,.0f}"
    roas_color = "success" if roas >= 2.0 else "warning" if roas >= 1.0 else "danger"

    cards = [
        _kpi_card(f"Total {kpi_col}", fmt_kpi, "primary"),
        _kpi_card("Total Media Spend", f"${total_spend:,.0f}", "secondary"),
        _kpi_card("Blended ROAS", f"{roas:.1f}×", roas_color),
    ]

    # ── ROI horizontal bar chart ───────────────────────────────────────────
    agg = (
        paid.groupby("channel")
        .agg(
            total_contrib=("contribution", "sum"),
            total_spend=("spend", "sum"),
            roi_lower_90=("roi_lower_90", "first"),
            roi_upper_90=("roi_upper_90", "first"),
        )
        .reset_index()
    )
    agg["roi"] = agg["total_contrib"] / agg["total_spend"].replace(0, float("nan"))
    agg = agg.dropna(subset=["roi"]).sort_values("roi")

    roi_fig = go.Figure()
    for _, row in agg.iterrows():
        ch = row["channel"]
        roi = row["roi"]
        err_lo = max(roi - (row["roi_lower_90"] or roi), 0)
        err_hi = max((row["roi_upper_90"] or roi) - roi, 0)
        roi_fig.add_trace(
            go.Bar(
                x=[roi],
                y=[ch],
                orientation="h",
                marker_color=COLORS.get(ch, "#636EFA"),
                error_x=dict(
                    type="data",
                    symmetric=False,
                    array=[err_hi],
                    arrayminus=[err_lo],
                    color="#888",
                    thickness=1.5,
                    width=6,
                ),
                text=[f"  {roi:.1f}×"],
                textposition="outside",
                showlegend=False,
            )
        )
    roi_fig.update_layout(
        title=dict(text="ROI by Channel  (90% CI)", font=dict(size=13, color="#495057")),
        xaxis=dict(title="Return on Investment (×)", gridcolor="#F0F0F0", zeroline=False),
        yaxis=dict(title="", tickfont=dict(size=12)),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=10, r=70, t=44, b=30),
        height=360,
    )

    # ── Attribution donut ──────────────────────────────────────────────────
    agg_all = (
        contributions.groupby("channel")["contribution"].sum().reset_index()
    )
    agg_all = agg_all[agg_all["contribution"] > 0]
    pie_colors = [COLORS.get(ch, "#636EFA") for ch in agg_all["channel"]]

    pie_fig = go.Figure(
        go.Pie(
            labels=agg_all["channel"],
            values=agg_all["contribution"],
            hole=0.44,
            marker=dict(colors=pie_colors, line=dict(color="white", width=2)),
            textinfo="label+percent",
            textposition="outside",
            showlegend=False,
        )
    )
    pie_fig.update_layout(
        title=dict(text=f"{kpi_col} Attribution", font=dict(size=13, color="#495057")),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=44, b=10),
        height=360,
    )

    # ── Weekly stacked area ────────────────────────────────────────────────
    stack_order = ["Baseline"] + channels + organic_chs
    ts_fig = go.Figure()
    for ch in stack_order:
        ch_data = contributions[contributions["channel"] == ch].sort_values("date")
        if ch_data.empty:
            continue
        ts_fig.add_trace(
            go.Scatter(
                x=ch_data["date"],
                y=ch_data["contribution"],
                name=ch,
                stackgroup="one",
                mode="none",
                fillcolor=COLORS.get(ch, "#ADB5BD"),
                hovertemplate=(
                    f"<b>{ch}</b><br>"
                    "%{x|%b %d, %Y}<br>"
                    f"{kpi_col}: %{{y:$,.0f}}<extra></extra>"
                    if is_revenue
                    else f"<b>{ch}</b><br>%{{x|%b %d, %Y}}<br>{kpi_col}: %{{y:,.0f}}<extra></extra>"
                ),
            )
        )
    ts_fig.update_layout(
        title=dict(
            text=f"Weekly {kpi_col} — Baseline + Channel Contributions",
            font=dict(size=13, color="#495057"),
        ),
        xaxis=dict(title="", showgrid=True, gridcolor="#F0F0F0"),
        yaxis=dict(
            title=kpi_col,
            tickformat="$,.0f" if is_revenue else ",.0f",
            gridcolor="#F0F0F0",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(
            orientation="h",
            y=-0.18,
            x=0,
            font=dict(size=11),
        ),
        margin=dict(l=10, r=10, t=44, b=90),
        height=440,
        hovermode="x unified",
    )

    return title, cards, roi_fig, pie_fig, ts_fig


# ── Component helpers ─────────────────────────────────────────────────────────


def _kpi_card(label: str, value: str, color: str) -> dbc.Col:
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
        width=12,
        md=4,
    )


def _placeholder_fig(message: str = "Select a client to view results") -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                showarrow=False,
                font=dict(size=13, color="#ADB5BD"),
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
            )
        ],
        margin=dict(l=0, r=0, t=0, b=0),
        height=340,
    )
    return fig


def _no_data_fig() -> go.Figure:
    return _placeholder_fig("No model output yet — run the Meridian notebook first")
