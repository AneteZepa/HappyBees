import os
import sys
import logging
import argparse
from dash import Dash, html, dcc, Output, Input, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
import httpx
import pandas as pd
from flask import request

# --- 1. CLI ARGUMENT PARSING ---
# We use parse_known_args because Dash/Flask might try to interpret other args
parser = argparse.ArgumentParser(description="BeeWatch Dashboard")
parser.add_argument("--node", default="pico-hive-001", help="Target Node ID (default: pico-hive-001)")
parser.add_argument("--api", default="http://localhost:8000/api/v1", help="API URL (default: http://localhost:8000/api/v1)")
args, unknown = parser.parse_known_args()

NODE_ID = args.node
API_URL = args.api

print(f"\n[INIT] Dashboard targeting Node: {NODE_ID}")
print(f"[INIT] API Endpoint: {API_URL}\n")

# --- 2. RIGOROUS PATH VALIDATION ---
# Calculate absolute paths to ensure no ambiguity
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Assets are one level up from 'dashboard/' in 'assets/'
ASSETS_PATH = os.path.join(os.path.dirname(CURRENT_DIR), 'assets')

# Validate existence immediately
if not os.path.exists(ASSETS_PATH):
    print(f"\n[CRITICAL ERROR] Assets directory not found at: {ASSETS_PATH}")
    print(f"Current Directory: {CURRENT_DIR}")
    print("Please ensure you are running from the project root.\n")
    sys.exit(1)

# Check specific files
required_files = ['style.css', 'beewatch_logo.png']
missing_files = [f for f in required_files if not os.path.exists(os.path.join(ASSETS_PATH, f))]
if missing_files:
    print(f"\n[CRITICAL ERROR] Missing required assets in {ASSETS_PATH}: {missing_files}\n")
    sys.exit(1)

print(f"[INIT] Asset folder resolved: {ASSETS_PATH}")
print(f"[INIT] Validated files: {required_files}")

# --- 3. DASHBOARD SETUP ---
# Silence standard werkzeug logs to make our custom asset logs clearer
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Dash(
    __name__, 
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    assets_folder=ASSETS_PATH,
    title=f"BEEWATCH: {NODE_ID}"
)

# Hook into the underlying Flask server to log asset requests
@app.server.before_request
def log_request_info():
    if "/assets/" in request.path:
        print(f"[ASSET REQUEST] {request.path} -> ", end="")

@app.server.after_request
def log_response_info(response):
    if "/assets/" in request.path:
        print(f"{response.status_code}")
    return response

# --- HELPER COMPONENTS ---

def make_header():
    return dbc.Row([
        # FIX: Logo 30% bigger (110px), No Glow Filter
        dbc.Col(html.Img(src=app.get_asset_url("beewatch_logo.png"), style={"height": "110px"}), width="auto"),
        dbc.Col([
            html.H1("BEEWATCH SYSTEMS", className="retro-glow m-0"),
            html.Div(f"TARGET: {NODE_ID} // STATUS: MONITORING", className="small text-white", style={"letterSpacing": "2px", "opacity": "0.8"})
        ], className="d-flex flex-column justify-content-center ps-4")
    ], className="mb-4 border-bottom border-warning pb-3")

def div_card(title, content, height=None):
    style = {}
    if height: style["height"] = height
    return html.Div([
        html.Div(title, className="retro-card-header"),
        html.Div(content, className="retro-card-body", style=style)
    ], className="retro-card")

def make_stat_display(label, id_val, unit):
    return div_card(label, html.Div([
        html.H2("--", id=id_val, className="retro-glow text-center m-0", style={"fontSize": "3rem"}),
        html.Div(unit, className="text-center text-white small")
    ]))

def make_controls():
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
        html.Div(id="cmd-status", className="text-center small text-white mt-3 fst-italic", children="STATUS: READY")
    ])

# --- LAYOUT ---

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
            # Graph
            dbc.Col(div_card("ENVIRONMENTAL_HISTORY", 
                dcc.Graph(id="live-chart", config={'displayModeBar': False}, style={"height": "320px"})
            ), width=8),
            
            # Terminal
            dbc.Col(html.Div([
                html.Div("SERIAL_UPLINK", className="retro-card-header"),
                html.Div(id="terminal-output", className="terminal-window"),
                dcc.Interval(id="term-updater", interval=1000) # 1s poll for logs
            ], className="retro-card"), width=4),
        ]),

        dcc.Interval(id="data-updater", interval=2000), # 2s poll for data
        
        # Hidden div to test CSS loading logic
        html.Div(id="css-validator", className="retro-glow", style={"display": "none"})
    ], className="retro-container")
])

# --- CALLBACKS ---

# 1. Update Metrics & Chart
@app.callback(
    [Output("val-temp", "children"), 
     Output("val-hum", "children"),
     Output("live-chart", "figure")],
    [Input("data-updater", "n_intervals")]
)
def update_data(_):
    try:
        r = httpx.get(f"{API_URL}/telemetry/?node_id={NODE_ID}&limit=100")
        if r.status_code != 200: raise Exception("API Error")
        data = r.json()
        if not data: raise Exception("No Data")
        
        # Stats
        latest = data[0]
        temp_txt = f"{latest['temperature_c']:.1f}"
        hum_txt = f"{latest['humidity_pct']:.1f}"
        
        # Plot
        df = pd.DataFrame(data)
        
        fig = go.Figure()
        
        # Temperature Line
        fig.add_trace(go.Scatter(
            x=df['time'], y=df['temperature_c'], 
            name='TEMP', 
            line=dict(color='#FFD700', width=2), 
            mode='lines'
        ))
        
        # Humidity Line (Secondary Axis)
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
            yaxis=dict(title="Temp (C)", gridcolor='rgba(255,255,255,0.1)', showgrid=True),
            yaxis2=dict(title="Hum (%)", overlaying='y', side='right', showgrid=False),
            xaxis=dict(gridcolor='rgba(255,255,255,0.1)', showgrid=True),
            legend=dict(orientation="h", y=1.1, x=0),
            hovermode="x unified"
        )
        
        return temp_txt, hum_txt, fig

    except Exception:
        # Return placeholders on error
        empty_fig = go.Figure()
        empty_fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, showticklabels=False),
            yaxis=dict(showgrid=False, showticklabels=False)
        )
        return "--", "--", empty_fig

# 2. Update Terminal Log
@app.callback(
    Output("terminal-output", "children"),
    [Input("term-updater", "n_intervals")]
)
def update_terminal(_):
    try:
        r = httpx.get(f"{API_URL}/logs/?node_id={NODE_ID}&limit=50")
        if r.status_code != 200: return []
        logs = r.json()
        
        return [
            html.Div([
                html.Span(f"[{log['created_at'][11:19]}] ", className="log-timestamp"),
                html.Span(log['message'])
            ], className="log-entry") for log in logs
        ]
    except:
        return html.Div("CONNECTION_LOST...", className="text-danger")

# 3. Handle Buttons
@app.callback(
    Output("cmd-status", "children"),
    [Input(f"btn-{k}", "n_clicks") for k in ['s','w','t','a','m','c','d','p']],
    prevent_initial_call=True
)
def handle_commands(*args):
    ctx = callback_context
    if not ctx.triggered: return "STATUS: READY"
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0].split('-')[1]
    
    # Map button ID to Protocol Command
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
    
    # Specific params
    if button_id == "s": params = {"model": "summer"}
    if button_id == "w": params = {"model": "winter"}
        
    try:
        httpx.post(f"{API_URL}/commands/", json={
            "node_id": NODE_ID, 
            "command_type": cmd_type,
            "params": params
        })
        return f"STATUS: TRANSMITTED [{cmd_type}]"
    except:
        return "STATUS: TRANSMISSION FAILED"

if __name__ == "__main__":
    print("[INIT] Starting Dash server on port 8050...")
    app.run(debug=True, port=8050)
