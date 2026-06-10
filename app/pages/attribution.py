"""
app/pages/attribution.py
~~~~~~~~~~~~~~~~~~~~~~~~
Attribution triangulation — MMM incremental ROI vs last-touch ROI side by side.

Shows, per channel, the difference between what the MMM says a channel contributed
(incremental leads per dollar, with credible intervals) and what last-touch
attribution reports (raw attributed leads per dollar of spend).

The gap between the two is the point: MMM strips out baseline and applies adstock;
last-touch is direct attribution. Stakeholders should see where the models agree
and where they diverge.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import dash
from dash import Input, Output, callback, dcc, html, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import pandas as pd

import data as app_data

dash.register_page(__name__, path="/attribution", title="Attribution — MMM Workbench")

COLORS = app_data.CHANNEL_COLORS
MMM_COLOR = "#4C72B0"
LT_COLOR = "#E67E22"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _aggregate_mmm(contrib: pd.DataFrame, date_min: str, date_max: str) -> pd.DataFrame:
    """Aggregate contributions over [date_min, date_max] and compute period ROI."""
    mask = (contrib["date"] >= pd.Timestamp(date_min)) & (contrib["date"] <= pd.Timestamp(date_max))
    filtered = contrib[mask & (contrib["channel_type"] == "paid")].copy()
    if filtered.empty:
        return pd.DataFrame(columns=["channel", "mmm_roi", "roi_lower_90", "roi_upper_90", "mmm_leads", "mmm_spend"])

    agg = (
        filtered.groupby("channel", as_index=False)
        .agg(
            mmm_leads=("contribution", "sum"),
            mmm_spend=("spend", "sum"),
            roi_lower_90=("roi_lower_90", "median"),
            roi_upper_90=("roi_upper_90", "median"),
        )
    )
    agg["mmm_roi"] = agg.apply(
        lambda r: r["mmm_leads"] / r["mmm_spend"] if r["mmm_spend"] > 0 else None, axis=1
    )
    return agg


def _aggregate_lt(lt: pd.DataFrame, date_min: str, date_max: str) -> pd.DataFrame:
    """Aggregate last-touch data over [date_min, date_max]."""
    mask = (lt["week"] >= pd.Timestamp(date_min)) & (lt["week"] <= pd.Timestamp(date_max))
    filtered = lt[mask].copy()
    if filtered.empty:
        return pd.DataFrame(columns=["channel", "lt_leads", "lt_spend", "lt_roi"])

    agg = (
        filtered.groupby("channel", as_index=False)
        .agg(lt_leads=("lt_leads", "sum"), lt_spend=("lt_spend", "sum"))
    )
    agg["lt_roi"] = agg.apply(
        lambda r: r["lt_leads"] / r["lt_spend"] if r["lt_spend"] > 0 else None, axis=1
    )
    return agg


def _merge_for_comparison(mmm_agg: pd.DataFrame, lt_agg: pd.DataFrame) -> pd.DataFrame:
    """Outer-join MMM and LT aggregates on channel. Handles one or both sides being empty."""
    if lt_agg.empty and not mmm_agg.empty:
        return mmm_agg.sort_values("mmm_roi", ascending=False, na_position="last").reset_index(drop=True)
    if mmm_agg.empty and not lt_agg.empty:
        return lt_agg.sort_values("lt_roi", ascending=False, na_position="last").reset_index(drop=True)
    if mmm_agg.empty and lt_agg.empty:
        return pd.DataFrame()
    merged = mmm_agg.merge(lt_agg, on="channel", how="outer")
    return merged.sort_values("mmm_roi", ascending=False, na_position="last").reset_index(drop=True)


# ── Layout ────────────────────────────────────────────────────────────────────

layout = dbc.Container(
    [
        dbc.Row(
            dbc.Col(
                [
                    html.H4(id="attr-title", className="text-primary fw-bold mb-1"),
                    html.P(
                        "MMM incremental ROI vs. last-touch ROI by channel. "
                        "MMM removes baseline and applies adstock; last-touch is raw attributed leads per dollar. "
                        "The gap between them is the signal.",
                        className="text-muted small mb-0",
                    ),
                ],
                width=12,
            ),
            className="mb-3",
        ),
        # Date range picker
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.Label("Date range", className="form-label small fw-medium mb-1"),
                        dcc.DatePickerRange(
                            id="attr-date-range",
                            display_format="MMM D, YYYY",
                            className="d-block",
                        ),
                    ],
                    width=12,
                    md=6,
                    lg=5,
                ),
                dbc.Col(
                    html.Div(id="attr-mmm-only-callout"),
                    width=12,
                    md=6,
                    lg=7,
                    className="d-flex align-items-end",
                ),
            ],
            className="mb-4",
        ),
        # LT unavailable banner
        dbc.Row(
            dbc.Col(html.Div(id="attr-lt-banner"), width=12),
            className="mb-2",
        ),
        # Primary chart: ROI comparison
        dbc.Row(
            dbc.Col(
                html.Div(dcc.Graph(id="attr-roi-chart"), className="chart-card"),
                width=12,
                className="mb-4",
            )
        ),
        # Secondary chart: lead share comparison
        dbc.Row(
            dbc.Col(
                html.Div(dcc.Graph(id="attr-share-chart"), className="chart-card"),
                width=12,
                className="mb-4",
            )
        ),
        # Summary table
        dbc.Row(
            dbc.Col(
                html.Div(
                    [
                        html.H6("Channel Summary", className="fw-semibold mb-3"),
                        html.Div(id="attr-summary-table"),
                    ],
                    className="chart-card",
                ),
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
    Output("attr-title", "children"),
    Output("attr-date-range", "min_date_allowed"),
    Output("attr-date-range", "max_date_allowed"),
    Output("attr-date-range", "start_date"),
    Output("attr-date-range", "end_date"),
    Input("client-store", "data"),
)
def init_page(client_id: str | None):
    client_id = client_id or "freedom_power"
    label = client_id.replace("_", " ").title()

    contrib = app_data.get_contributions(client_id)
    if contrib is not None and not contrib.empty:
        min_date = contrib["date"].min().date().isoformat()
        max_date = contrib["date"].max().date().isoformat()
    else:
        min_date = "2024-01-01"
        max_date = pd.Timestamp.today().date().isoformat()

    return f"{label} — Attribution Triangulation", min_date, max_date, min_date, max_date


@callback(
    Output("attr-lt-banner", "children"),
    Output("attr-mmm-only-callout", "children"),
    Output("attr-roi-chart", "figure"),
    Output("attr-share-chart", "figure"),
    Output("attr-summary-table", "children"),
    Input("client-store", "data"),
    Input("attr-date-range", "start_date"),
    Input("attr-date-range", "end_date"),
)
def update_charts(client_id: str | None, start_date: str | None, end_date: str | None):
    client_id = client_id or "freedom_power"

    if not start_date or not end_date:
        empty_fig = go.Figure()
        empty_fig.update_layout(template="plotly_white")
        return None, None, empty_fig, empty_fig, None

    contrib = app_data.get_contributions(client_id)
    lt = app_data.get_last_touch(client_id)

    # ── LT unavailable banner ─────────────────────────────────────────────────
    lt_banner = None
    if lt is None:
        lt_banner = dbc.Alert(
            "Last-touch data unavailable — BigQuery credentials not found or "
            "this client has no last_touch config. MMM data shown below.",
            color="warning",
            className="py-2 small",
        )

    # ── MMM-only channels callout ─────────────────────────────────────────────
    mmm_only_callout = None
    if contrib is not None:
        lt_channels = set(lt["channel"].unique()) if lt is not None else set()
        mmm_channels = set(
            contrib.loc[contrib["channel_type"] == "paid", "channel"].unique()
        )
        mmm_only = sorted(mmm_channels - lt_channels)
        if mmm_only:
            ch_list = ", ".join(c.replace("_", " ") for c in mmm_only)
            mmm_only_callout = dbc.Alert(
                [
                    html.Strong("MMM-only channels: "),
                    f"{ch_list}. These appear in the model but have no last-touch counterpart.",
                ],
                color="info",
                className="py-2 small mb-0",
            )

    # ── Aggregate both sides ──────────────────────────────────────────────────
    mmm_agg = pd.DataFrame()
    if contrib is not None:
        mmm_agg = _aggregate_mmm(contrib, start_date, end_date)

    lt_agg = pd.DataFrame()
    if lt is not None:
        lt_agg = _aggregate_lt(lt, start_date, end_date)

    if mmm_agg.empty and lt_agg.empty:
        msg = "No data available for the selected period."
        empty_fig = go.Figure().update_layout(
            template="plotly_white",
            annotations=[{"text": msg, "showarrow": False, "font": {"size": 14}}],
        )
        return lt_banner, mmm_only_callout, empty_fig, empty_fig, html.P(msg, className="text-muted")

    merged = _merge_for_comparison(mmm_agg, lt_agg)
    channels = merged["channel"].tolist()

    # ── ROI comparison bar chart ──────────────────────────────────────────────
    roi_fig = go.Figure()

    if not mmm_agg.empty:
        roi_fig.add_trace(go.Bar(
            name="MMM ROI",
            x=channels,
            y=merged["mmm_roi"],
            marker_color=MMM_COLOR,
            error_y=dict(
                type="data",
                symmetric=False,
                array=(merged["roi_upper_90"] - merged["mmm_roi"]).clip(lower=0),
                arrayminus=(merged["mmm_roi"] - merged["roi_lower_90"]).clip(lower=0),
                visible=True,
                thickness=2,
                width=6,
            ),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "MMM ROI: %{y:.3f}<br>"
                "<extra></extra>"
            ),
        ))

    if not lt_agg.empty:
        roi_fig.add_trace(go.Bar(
            name="Last-touch ROI",
            x=channels,
            y=merged["lt_roi"],
            marker_color=LT_COLOR,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "LT ROI: %{y:.3f}<br>"
                "<extra></extra>"
            ),
        ))

    roi_fig.update_layout(
        title="ROI by Channel: MMM (incremental) vs. Last-touch (attributed)",
        yaxis_title="Leads per $1 spend",
        xaxis_title="",
        barmode="group",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60, b=40),
    )

    # ── Lead share comparison chart ───────────────────────────────────────────
    share_fig = go.Figure()

    if not mmm_agg.empty:
        total_mmm = merged["mmm_leads"].sum()
        mmm_share = (merged["mmm_leads"] / total_mmm * 100).round(1) if total_mmm > 0 else merged["mmm_leads"] * 0
        share_fig.add_trace(go.Bar(
            name="MMM lead share",
            x=channels,
            y=mmm_share,
            marker_color=MMM_COLOR,
            hovertemplate="<b>%{x}</b><br>MMM: %{y:.1f}%<extra></extra>",
        ))

    if not lt_agg.empty:
        total_lt = merged["lt_leads"].sum()
        lt_share = (merged["lt_leads"] / total_lt * 100).round(1) if total_lt > 0 else merged["lt_leads"] * 0
        share_fig.add_trace(go.Bar(
            name="Last-touch lead share",
            x=channels,
            y=lt_share,
            marker_color=LT_COLOR,
            hovertemplate="<b>%{x}</b><br>LT: %{y:.1f}%<extra></extra>",
        ))

    share_fig.update_layout(
        title="Lead Share by Channel: MMM vs. Last-touch",
        yaxis_title="% of total leads",
        xaxis_title="",
        barmode="group",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60, b=40),
    )

    # ── Summary table ─────────────────────────────────────────────────────────
    rows = []
    for _, r in merged.iterrows():
        mmm_roi = r.get("mmm_roi")
        lt_roi = r.get("lt_roi")
        ci_lo = r.get("roi_lower_90")
        ci_hi = r.get("roi_upper_90")

        delta = (mmm_roi - lt_roi) if (mmm_roi is not None and lt_roi is not None and
                                        not pd.isna(mmm_roi) and not pd.isna(lt_roi)) else None
        pct_diff = (delta / lt_roi * 100) if (delta is not None and lt_roi and lt_roi != 0) else None

        rows.append({
            "Channel": r["channel"].replace("_", " "),
            "MMM ROI": f"{mmm_roi:.3f}" if pd.notna(mmm_roi) and mmm_roi is not None else "—",
            "MMM 90% CI": (
                f"[{ci_lo:.3f}, {ci_hi:.3f}]"
                if (pd.notna(ci_lo) and pd.notna(ci_hi) and ci_lo is not None and ci_hi is not None)
                else "—"
            ),
            "LT ROI": f"{lt_roi:.3f}" if pd.notna(lt_roi) and lt_roi is not None else "—",
            "Δ (MMM – LT)": f"{delta:+.3f}" if delta is not None else "—",
            "% Diff": f"{pct_diff:+.1f}%" if pct_diff is not None else "—",
        })

    table = dash_table.DataTable(
        data=rows,
        columns=[{"name": c, "id": c} for c in rows[0]] if rows else [],
        style_table={"overflowX": "auto"},
        style_header={"fontWeight": "bold", "backgroundColor": "#f1f3f5", "border": "1px solid #dee2e6"},
        style_cell={"padding": "8px 12px", "fontSize": "13px", "border": "1px solid #dee2e6"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"},
        ],
    )

    return lt_banner, mmm_only_callout, roi_fig, share_fig, table
