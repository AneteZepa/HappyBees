"""
HappyBees Dashboard

Retro-futuristic real-time monitoring interface using Dash/Plotly.

Usage:
    python -m backend.dashboard.app --node pico-hive-001
    python -m backend.dashboard.app --node pico-hive-001 --api http://localhost:8000/api/v1
"""

import os
import sys
import logging
import argparse
from dash import Dash, html, dcc, Output, Input, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
import httpx
import pandas as pd
from flask import request

# Parse command line arguments
parser = argparse.ArgumentParser(description="HappyBees Dashboard")
parser.add_argument("--node", default="pico-hive-001", help="Target Node ID")
parser.add_argument("--api", default="http://localhost:8000/api/v1", help="API URL")
args, unknown = parser.parse_known_args()

NODE_ID = args.node
API_URL = args.api

print(f"\n[INIT] Dashboard targeting Node: {NODE_ID}")
print(f"[INIT] API Endpoint: {API_URL}\n")

# Resolve assets path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_PATH = os.path.join(os.path.dirname(CURRENT_DIR), 'assets')

if not os.path.exists(ASSETS_PATH):
    print(f"[WARNING] Assets directory not found at: {ASSETS_PATH}")
    ASSETS_PATH = None

# Silence werkzeug logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Create Dash app
app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    assets_folder=ASSETS_PATH,
    title=f"HAPPYBEES: {NODE_ID}"
)


def make_header():
    """Create header component."""
    return dbc.Row([
        dbc.Col([
            html.H1("HAPPYBEES SYSTEMS", className="retro-glow m-0"),
            html.Div(
                f"TARGET: {NODE_ID} // STATUS: MONITORING",
                className="small text-white",
                style={"letterSpacing": "2px", "opacity": "0.8"}
            )
        ], className="d-flex flex-column justify-content-center")
    ], className="mb-4 border-bottom border-warning pb-3")


def div_card(title, content, height=None):
    """Create a styled card component."""
    style = {}
    if height:
        style["height"] = height
    return html.Div([
        html.Div(title, className="retro-card-header"),
        html.Div(content, className="retro-card-body", style=style)
    ], className="retro-card")


def make_stat_display(label, id_val, unit):
    """Create a stat display card."""
    return div_card(label, html.Div([
        html.H2("--", id=id_val, className="retro-glow text-center m-0",
                style={"fontSize": "3rem"}),
        html.Div(unit, className="text-center text-white small")
    ]))


def make_controls():
    """Create control panel."""
    return div_card("CONTROL_INTERFACE", [
        dbc.Row([
            dbc.Col(dbc.Button("S | SUMMER INFER", id="btn-s", className="retro-btn"), width=6),
            dbc.Col(dbc.Button("W | WINTER INFER", id="btn-w", className="retro-btn"), width=6),
        ], className="g-0 mb-1"),
        dbc.Row([
            dbc.Col(dbc.Button("T | READ SENSORS", id="btn-t", className="retro-btn"), width=6),
            dbc.Col(dbc.Button("A | AUDIO STREAM", id="btn-a", className="retro-btn"), width=6),
        ], className="g-0 mb-1"),
        dbc.Row([
            dbc.Col(dbc.Button("M | TOGGLE MOCK", id="btn-m", className="retro-btn"), width=6),
            dbc.Col(dbc.Button("C | CLEAR HIST", id="btn-c", className="retro-btn"), width=6),
        ], className="g-0 mb-1"),
        dbc.Row([
            dbc.Col(dbc.Button("D | DEBUG DUMP", id="btn-d", className="retro-btn"), width=6),
            dbc.Col(dbc.Button("P | PING DEVICE", id="btn-p", className="retro-btn"), width=6),
        ], className="g-0"),
        html.Div(
            id="cmd-status",
            className="text-center small text-white mt-3 fst-italic",
            children="STATUS: READY"
        )
    ])


# Layout
app.layout = html.Div([
    dbc.Container([
        make_header(),

        # Row 1: Metrics & Controls
        dbc.Row([
            dbc.Col(make_stat_display("TEMPERATURE", "val-temp", "CELSIUS"), width=3),
            dbc.Col(make_stat_display("HUMIDITY", "val-hum", "PERCENT"), width=3),
            dbc.Col(make_controls(), width=6),
        ], className="mb-4"),

        # Row 2: Graph & Terminal
        dbc.Row([
            dbc.Col(div_card("ENVIRONMENTAL_HISTORY",
                dcc.Graph(id="live-chart", config={'displayModeBar': False},
                         style={"height": "320px"})
            ), width=8),
            dbc.Col(html.Div([
                html.Div("SERIAL_UPLINK", className="retro-card-header"),
                html.Div(id="terminal-output", className="terminal-window"),
                dcc.Interval(id="term-updater", interval=1000)
            ], className="retro-card"), width=4),
        ]),

        dcc.Interval(id="data-updater", interval=2000),
    ], className="retro-container")
])


@app.callback(
    [Output("val-temp", "children"),
     Output("val-hum", "children"),
     Output("live-chart", "figure")],
    [Input("data-updater", "n_intervals")]
)
def update_data(_):
    """Update metrics and chart."""
    try:
        r = httpx.get(f"{API_URL}/telemetry/?node_id={NODE_ID}&limit=100")
        if r.status_code != 200:
            raise Exception("API Error")
        data = r.json()
        if not data:
            raise Exception("No Data")

        latest = data[-1]
        temp_txt = f"{latest['temperature_c']:.1f}"
        hum_txt = f"{latest['humidity_pct']:.1f}"

        df = pd.DataFrame(data)
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df['time'], y=df['temperature_c'],
            name='TEMP',
            line=dict(color='#FFD700', width=2),
            mode='lines'
        ))

        fig.add_trace(go.Scatter(
            x=df['time'], y=df['humidity_pct'],
            name='HUM',
            line=dict(color='#FFFFFF', width=1, dash='dot'),
            yaxis='y2'
        ))

        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#FFD700', family="Exo"),
            margin=dict(l=50, r=50, t=20, b=40),
            yaxis=dict(title="Temp (C)", gridcolor='rgba(255,255,255,0.1)'),
            yaxis2=dict(title="Hum (%)", overlaying='y', side='right', showgrid=False),
            xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
            legend=dict(orientation="h", y=1.1, x=0),
            hovermode="x unified"
        )

        return temp_txt, hum_txt, fig

    except Exception:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, showticklabels=False),
            yaxis=dict(showgrid=False, showticklabels=False)
        )
        return "--", "--", empty_fig


@app.callback(
    Output("terminal-output", "children"),
    [Input("term-updater", "n_intervals")]
)
def update_terminal(_):
    """Update terminal log display."""
    try:
        r = httpx.get(f"{API_URL}/logs/?node_id={NODE_ID}&limit=50")
        if r.status_code != 200:
            return []
        logs = r.json()

        return [
            html.Div([
                html.Span(f"[{log['created_at'][11:19]}] ", className="log-timestamp"),
                html.Span(log['message'])
            ], className="log-entry") for log in logs
        ]
    except Exception:
        return html.Div("CONNECTION_LOST...", className="text-danger")


@app.callback(
    Output("cmd-status", "children"),
    [Input(f"btn-{k}", "n_clicks") for k in ['s', 'w', 't', 'a', 'm', 'c', 'd', 'p']],
    prevent_initial_call=True
)
def handle_commands(*args):
    """Handle control button clicks."""
    ctx = callback_context
    if not ctx.triggered:
        return "STATUS: READY"

    button_id = ctx.triggered[0]['prop_id'].split('.')[0].split('-')[1]

    cmd_map = {
        "s": "RUN_INFERENCE",
        "w": "RUN_INFERENCE",
        "t": "READ_CLIMATE",
        "a": "CAPTURE_AUDIO",
        "m": "TOGGLE_MOCK",
        "c": "CLEAR_HISTORY",
        "d": "DEBUG_DUMP",
        "p": "PING"
    }

    cmd_type = cmd_map.get(button_id)
    params = {}

    if button_id == "s":
        params = {"model": "summer"}
    if button_id == "w":
        params = {"model": "winter"}

    try:
        httpx.post(f"{API_URL}/commands/", json={
            "node_id": NODE_ID,
            "command_type": cmd_type,
            "params": params
        })
        return f"STATUS: TRANSMITTED [{cmd_type}]"
    except Exception:
        return "STATUS: TRANSMISSION FAILED"


if __name__ == "__main__":
    print("[INIT] Starting Dash server on port 8050...")
    app.run(debug=True, port=8050)
