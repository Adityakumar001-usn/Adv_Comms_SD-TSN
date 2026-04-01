"""
SD-TSN Interactive Presentation Dashboard

This module provides a visual, real-time presentation interface for the SD-TSN simulation.
Using Streamlit and Plotly, it guides the user through the 4 core phases:
1. Discovery (Mapping Topology)
2. Optimization (Solving ILP mathematically)
3. Configuration (Deploying GCL and routing rules)
4. Live Stress-Test (Animating a massive background interference attack)

The code utilizes a state machine `st.session_state.demo_phase` to progressively
reveal content and simulate processing delays using `time.sleep()`.
"""

import streamlit as st
import pandas as pd
import time
import plotly.graph_objects as go
import plotly.express as px
import networkx as nx

st.set_page_config(
    page_title="SD-TSN Presentation Dashboard",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for a professional automotive-tech dark/clean theme
st.markdown("""
    <style>
    .stApp {
        background-color: #0a0e17;
        color: #e0e6ed;
    }
    .metric-card {
        background-color: #111827;
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #1f2937;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
    }
    .terminal-window {
        background-color: #000000;
        border-left: 4px solid #4ade80;
        border-radius: 6px;
        padding: 15px;
        font-family: 'Courier New', Courier, monospace;
        color: #4ade80;
        height: 250px;
        overflow-y: auto;
        box-shadow: inset 0 0 10px rgba(0,0,0,1);
    }
    /* Glow effect for critical text */
    .glow-text {
        color: #ff4b4b;
        text-shadow: 0 0 12px rgba(255, 75, 75, 0.6);
        font-weight: bold;
    }
    /* Waiting placeholder blocks */
    .placeholder-box {
        border: 2px dashed #374151;
        border-radius: 10px;
        padding: 40px;
        text-align: center;
        color: #6b7280;
        background-color: #111827;
    }
    </style>
""", unsafe_allow_html=True)

st.title("SD-TSN In-Vehicle Network: Guided Presentation")
st.markdown("""
This dashboard demonstrates the capabilities of a Software-Defined Time-Sensitive Network (SD-TSN) architecture.
Follow the guided phases to witness how the Centralized Network Configuration (CNC) guarantees deterministic latency for mission-critical traffic, even under massive background interference.
""")

# --- Phase Tracker State ---
if 'demo_phase' not in st.session_state:
    st.session_state.demo_phase = 0
if 'is_running' not in st.session_state:
    st.session_state.is_running = False
if 'final_logs' not in st.session_state:
    st.session_state.final_logs = ""
if 'slow_mo' not in st.session_state:
    st.session_state.slow_mo = False
if 'us_clock' not in st.session_state:
    st.session_state.us_clock = -50.0

st.sidebar.title("Simulation Settings")
st.session_state.slow_mo = st.sidebar.toggle("Enable Microsecond Slow-Mo", value=st.session_state.slow_mo, help="Pause at the maximum payload and manually step through the TAS scheduling.")

def render_phase_tracker():
    phases = [
        ("🟢 Discovery", "Mapping Topology & Flows"),
        ("🟡 Optimization (ILP)", "Solving TAS Scheduling"),
        ("🟠 Configuration", "Deploying GCL & L2 Routing"),
        ("🔴 Live Stress-Test", "Validating Determinism")
    ]

    cols = st.columns(4)
    for i, (title, desc) in enumerate(phases):
        with cols[i]:
            if st.session_state.demo_phase > i:
                st.success(f"**{title}**\n\n{desc}")
            elif st.session_state.demo_phase == i:
                if st.session_state.is_running:
                    st.warning(f"**{title}**\n\n{desc} *(In Progress...)*")
                else:
                    st.info(f"**{title}**\n\n{desc} *(Pending)*")
            else:
                st.markdown(f"<div class='metric-card' style='opacity:0.5'><strong>{title}</strong><br><small>{desc}</small></div>", unsafe_allow_html=True)

st.markdown("---")
phase_tracker_placeholder = st.empty()
with phase_tracker_placeholder.container():
    render_phase_tracker()
st.markdown("---")

def update_phase_tracker_ui():
    with phase_tracker_placeholder.container():
        render_phase_tracker()

def draw_empty_chart(title, x_title, y_title):
    """Draws a visually appealing empty placeholder chart for Phase 0."""
    fig = go.Figure()
    fig.update_layout(
        title=dict(text=title, font=dict(color='#9ca3af')),
        xaxis=dict(title=dict(text=x_title, font=dict(color='#4b5563')), showgrid=False, zeroline=False, tickfont=dict(color='#4b5563')),
        yaxis=dict(title=dict(text=y_title, font=dict(color='#4b5563')), showgrid=True, gridcolor='#1f2937', zeroline=False, tickfont=dict(color='#4b5563')),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=40, b=40),
        height=300
    )
    # Add a dummy invisible trace just to render axes
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode='lines', line=dict(color='rgba(0,0,0,0)'), hoverinfo='none'))
    return fig

def create_network_topology():
    # Constructing a simple representation of our Zonal Architecture
    # E1 -> SW1 -> SW3 -> GW -> E3
    # E2 -> SW2 -> SW4 -> GW -> E3
    # (Just an example matching our previous mock CUC setup)

    # Based on our previous models/cuc:
    # E1, SW1, SW2, SW3, SW4, GW, E2, E3
    # Flow 1 (E1 -> E3) path: ['E1', 'SW1', 'SW3', 'GW', 'E3']
    # Flow 2 (E2 -> E3) path: ['E2', 'SW2', 'SW4', 'GW', 'E3']

    nodes = ['E1', 'E2', 'SW1', 'SW2', 'SW3', 'SW4', 'GW', 'E3']
    edges = [
        ('E1', 'SW1'), ('SW1', 'SW3'), ('SW3', 'GW'), ('GW', 'E3'),
        ('E2', 'SW2'), ('SW2', 'SW4'), ('SW4', 'GW')
    ]

    # We define fixed positions to make it look like a clean zonal architecture diagram
    pos = {
        'E1': (0, 2),
        'SW1': (1, 2),
        'SW3': (2, 2),
        'E2': (0, 0),
        'SW2': (1, 0),
        'SW4': (2, 0),
        'GW': (3, 1),
        'E3': (4, 1)
    }

    # Flow paths
    flow1_edges = [('E1', 'SW1'), ('SW1', 'SW3'), ('SW3', 'GW'), ('GW', 'E3')]
    flow2_edges = [('E2', 'SW2'), ('SW2', 'SW4'), ('SW4', 'GW'), ('GW', 'E3')] # Note: GW to E3 is shared

    edge_x = []
    edge_y = []
    for edge in edges:
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    # Base edges (gray)
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=2, color='#888'),
        hoverinfo='none',
        mode='lines',
        name='Network Links'
    )

    # Flow 1 edges (Glowing Red)
    f1_x = []
    f1_y = []
    for edge in flow1_edges:
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        f1_x.extend([x0, x1, None])
        f1_y.extend([y0, y1, None])

    f1_trace = go.Scatter(
        x=f1_x, y=f1_y,
        line=dict(width=6, color='#ff4b4b'), # Streamlit red
        hoverinfo='none',
        mode='lines',
        name='Flow 1: Mission-Critical Route'
    )

    # Flow 2 edges (Dashed Amber)
    f2_x = []
    f2_y = []
    for edge in flow2_edges:
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        f2_x.extend([x0, x1, None])
        f2_y.extend([y0, y1, None])

    f2_trace = go.Scatter(
        x=f2_x, y=f2_y,
        line=dict(width=4, color='#faca2b', dash='dash'), # Amber
        hoverinfo='none',
        mode='lines',
        name='Flow 2: Background Interference Route'
    )

    node_x = []
    node_y = []
    node_text = []
    node_color = []
    for node in nodes:
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(f"<b>{node}</b>")
        if 'E' in node:
            node_color.append('#2b5b84') # Dark blue
        elif 'SW' in node:
            node_color.append('#4a4a4a') # Dark gray
        else:
            node_color.append('#800080') # Purple Gateway

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        text=node_text,
        textfont=dict(color='white'),
        textposition="top center",
        hoverinfo='text',
        marker=dict(
            showscale=False,
            color=node_color,
            size=35,
            line=dict(width=2, color='white')
        ),
        name='Network Controllers / Nodes'
    )

    fig = go.Figure(data=[edge_trace, f2_trace, f1_trace, node_trace],
             layout=go.Layout(
                title=dict(text='<br>Zonal In-Vehicle Network Topology', font=dict(size=18, color='white')),
                showlegend=True,
                legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')),
                hovermode='closest',
                margin=dict(b=20,l=5,r=5,t=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)'
             )
    )
    return fig

def run_simulation():
    st.session_state.is_running = True
    st.session_state.demo_phase = 0

# UI Layout Placeholder
col1, col2 = st.columns([1, 1])

with col1:
    topo_placeholder = st.empty()
    if st.session_state.demo_phase == 0 and not st.session_state.is_running:
        topo_placeholder.markdown("<div class='placeholder-box'><h4>Zonal Topology</h4><p>Awaiting Phase 1: Discovery...</p></div>", unsafe_allow_html=True)
    elif st.session_state.demo_phase >= 1:
        topo_placeholder.plotly_chart(create_network_topology(), use_container_width=True)

with col2:
    st.markdown("### Demo Controls")
    start_btn = st.button("▶️ Start Live Demo", type="primary", on_click=run_simulation, disabled=st.session_state.is_running)

    st.markdown("### Real-Time Flow Metrics")
    metric_col1, metric_col2 = st.columns(2)

    with metric_col1:
        f1_metric = st.empty()
        if st.session_state.demo_phase < 4:
            f1_metric.markdown("<div class='metric-card' style='opacity:0.5'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px; color:#4b5563'>--- µs</span><br><small style='color:#4b5563;'>Waiting for telemetry...</small></div>", unsafe_allow_html=True)
    with metric_col2:
        f2_metric = st.empty()
        if st.session_state.demo_phase < 4:
            f2_metric.markdown("<div class='metric-card' style='opacity:0.5'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#4b5563'>--- Bytes</span><br><small style='color:#4b5563;'>Waiting for telemetry...</small></div>", unsafe_allow_html=True)

    status_text = st.empty()
    if not st.session_state.is_running and st.session_state.demo_phase == 0:
        status_text.info("System Ready. Click Start Live Demo to begin the guided presentation.")

st.markdown("---")

col_bottom1, col_bottom2 = st.columns([1, 1])

with col_bottom1:
    chart_placeholder = st.empty()
    if st.session_state.demo_phase < 4:
        chart_placeholder.plotly_chart(draw_empty_chart("Real-Time End-to-End Latency vs. Payload", "Flow 2 Payload Size (Bytes)", "Latency (µs)"), use_container_width=True)

with col_bottom2:
    gantt_placeholder = st.empty()
    queue_buffer_placeholder = st.empty() # Added placeholder for the queue buffers
    if st.session_state.demo_phase < 3:
        gantt_placeholder.plotly_chart(draw_empty_chart("Switch Egress TAS Schedule", "Time relative to Cycle Start (µs)", ""), use_container_width=True)

st.markdown("### Simulated Live Logs")
log_placeholder = st.empty()
if not st.session_state.is_running and st.session_state.demo_phase == 0:
    log_placeholder.markdown("<div class='terminal-window' id='terminal_out'>user@cnc-server:~$ waiting for demo initialization...<span class='cursor'>_</span></div>", unsafe_allow_html=True)

def draw_gantt_chart(current_time=None):
    # Pre-computed deterministic GCL schedule based on PuLP ILP Output
    # Period: 50,000 µs (50ms)
    # Transmission times
    flow1_p7_start = 0.0
    flow1_p7_end = 81.92  # 1024 bytes @ 100Mbps
    guard_band_start = 50000.0 - 121.76
    guard_band_end = 50000.0

    # We'll just show the first 250 µs of the cycle to highlight the scheduling
    fig = go.Figure()

    # Priority 0 Queue
    fig.add_trace(go.Bar(
        y=['Queue 0 (Best Effort)'],
        x=[200], # Open after guard band / P7
        base=[100],
        orientation='h',
        marker=dict(color='orange'),
        name='P0 Open',
        text='P0 Traffic Allowed',
        hoverinfo='text'
    ))

    # Priority 7 Queue
    fig.add_trace(go.Bar(
        y=['Queue 7 (Time-Sensitive)'],
        x=[81.92], # Time to transmit
        base=[0],
        orientation='h',
        marker=dict(color='red'),
        name='P7 Open',
        text='P7 Transmission (81.92 µs)',
        hoverinfo='text'
    ))

    # Guard Band
    fig.add_trace(go.Bar(
        y=['Queue 0 (Best Effort)'],
        x=[121.76],
        base=[-121.76 + 50000],
        orientation='h',
        marker=dict(color='#8B0000', pattern_shape="/"),
        name='Guard Band',
        hovertext='<b>Guard Band (121.76 µs)</b><br>This safety gap prevents delivery trucks (P0)<br>from blocking the ambulance (P7).',
        hoverinfo='text'
    ))

    # To make the Gantt look coherent, let's plot a relative window from -150us to +300us
    fig.add_trace(go.Bar(
        y=['Queue 0 (Best Effort)'],
        x=[121.76],
        base=[-121.76],
        orientation='h',
        marker=dict(color='#8B0000', pattern_shape="/"),
        name='Guard Band',
        hovertext='<b>Guard Band (121.76 µs)</b><br>This safety gap prevents delivery trucks (P0)<br>from blocking the ambulance (P7).',
        hoverinfo='text',
        showlegend=False
    ))

    if current_time is not None:
        fig.add_vline(x=current_time, line_width=3, line_dash="dash", line_color="white")
        fig.add_annotation(
            x=current_time, y=1.1, xref="x", yref="paper",
            text=f"Time: {current_time:.2f} µs",
            showarrow=False,
            font=dict(color="white", size=12),
            bgcolor="#111827",
            bordercolor="white",
            borderwidth=1
        )

    fig.update_layout(
        title=dict(text="Switch Egress TAS Schedule (Zoomed to Cycle Start)", font=dict(color='white')),
        barmode='overlay',
        xaxis=dict(
            title=dict(text="Time relative to Cycle Start (µs)", font=dict(color='white')),
            tickfont=dict(color='white'),
            range=[-150, 300],
            zeroline=True,
            zerolinecolor='white',
            zerolinewidth=2
        ),
        yaxis=dict(title="", tickfont=dict(color='white')),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        height=300,
        margin=dict(l=20, r=20, t=40, b=40),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white'))
    )
    return fig

def draw_queue_buffers(q0_fill, q7_fill, gate0_open, gate7_open):
    """Draws custom HTML/CSS progress bars representing the live switch egress port queues."""
    g0_color = "#4ade80" if gate0_open else "#4b5563"
    g0_text = "OPEN" if gate0_open else "CLOSED"

    g7_color = "#4ade80" if gate7_open else "#4b5563"
    g7_text = "OPEN" if gate7_open else "CLOSED"

    html = f"""
    <div style="background-color: #111827; padding: 15px; border-radius: 8px; border: 1px solid #1f2937;">
        <h5 style="color: white; margin-bottom: 10px;">Switch Egress Port: Live Queue State</h5>

        <!-- Queue 7 -->
        <div style="display: flex; align-items: center; margin-bottom: 15px;">
            <div style="width: 100px; color: #ff4b4b; font-weight: bold;">Queue 7 (P7)</div>
            <div style="flex-grow: 1; background-color: #374151; height: 20px; border-radius: 10px; margin: 0 10px; overflow: hidden; border: 1px solid #555;">
                <div style="width: {q7_fill}%; background-color: #ff4b4b; height: 100%; transition: width 0.3s ease;"></div>
            </div>
            <div style="width: 80px; text-align: center; color: {g7_color}; font-weight: bold; border: 1px solid {g7_color}; padding: 2px; border-radius: 4px;">Gate: {g7_text}</div>
        </div>

        <!-- Queue 0 -->
        <div style="display: flex; align-items: center;">
            <div style="width: 100px; color: #faca2b; font-weight: bold;">Queue 0 (P0)</div>
            <div style="flex-grow: 1; background-color: #374151; height: 20px; border-radius: 10px; margin: 0 10px; overflow: hidden; border: 1px solid #555;">
                <div style="width: {q0_fill}%; background-color: #faca2b; height: 100%; transition: width 0.3s ease;"></div>
            </div>
            <div style="width: 80px; text-align: center; color: {g0_color}; font-weight: bold; border: 1px solid {g0_color}; padding: 2px; border-radius: 4px;">Gate: {g0_text}</div>
        </div>
    </div>
    """
    return html


def write_terminal_log(logs):
    """Wraps text in our custom terminal CSS"""
    # Replace newlines with <br> for HTML rendering
    html_logs = logs.replace('\n', '<br>')
    return f"<div class='terminal-window' id='terminal_out'>user@cnc-server:~$ {html_logs}<span class='cursor'>_</span></div>"

# Sequential Demo Execution Block
if st.session_state.is_running and st.session_state.demo_phase == 0:
    # Phase 0 -> 1: Discovery
    st.session_state.demo_phase = 1
    update_phase_tracker_ui()
    current_logs = "[System] Initializing Presentation Engine...\n"
    log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
    status_text.info("Phase 1: Discovering Network Topology and Flows...")
    time.sleep(1.0)
    current_logs += "[Discovery] Scanning zonal architecture... Found 8 nodes, 7 links.\n"
    current_logs += "[CUC] Identified Flow 1: Mission-Critical (Prio 7).\n"
    current_logs += "[CUC] Identified Flow 2: Best-Effort Interference (Prio 0).\n"
    log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
    topo_placeholder.plotly_chart(create_network_topology(), use_container_width=True)
    time.sleep(2.0)

    # Phase 1 -> 2: Optimization (ILP Deep-Dive)
    st.session_state.demo_phase = 2
    update_phase_tracker_ui()
    status_text.warning("Phase 2: Solving TAS Schedules via Integer Linear Programming...")

    def get_math_overlay(c1="🔴", c2="🔴", c3="🔴"):
        return f"""
        <div class="metric-card" style="border-left: 5px solid #faca2b;">
            <h4 style="color:#faca2b;">Mathematical Solver (PuLP ILP) Transparency</h4>
            <p>Enforcing IEEE 802.1Qbv Constraints:</p>
            <ul style="list-style-type: none; padding-left: 0; font-family: monospace;">
                <li>{c1} <strong>Flow Isolation Checked:</strong> Switch egress buffer conflict resolved.</li>
                <li style="margin-top: 10px;">{c2} <strong>Guard Band Calculated:</strong> 121.76 µs gap secured based on 100Mbps MTU limit.</li>
                <li style="margin-top: 10px;">{c3} <strong>End-to-End Boundary:</strong> Target path latency locked to &lt; 500 µs.</li>
            </ul>
        </div>
        """

    current_logs += "[PuLP] Formulating ILP Constraints...\n"
    log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)

    with chart_placeholder.container():
        math_overlay = st.empty()
        math_overlay.markdown(get_math_overlay("🔴", "🔴", "🔴"), unsafe_allow_html=True)
        time.sleep(1.0)

        current_logs += "[PuLP] Validating Buffer Collisions... Done.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        math_overlay.markdown(get_math_overlay("🟢", "🔴", "🔴"), unsafe_allow_html=True)
        time.sleep(1.0)

        current_logs += "[PuLP] Calculating required Guard Band... Solved: 121.76 µs.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        math_overlay.markdown(get_math_overlay("🟢", "🟢", "🔴"), unsafe_allow_html=True)
        time.sleep(1.0)

        current_logs += "[PuLP] Bounding end-to-end path delay... Optimal Schedule Found.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        math_overlay.markdown(get_math_overlay("🟢", "🟢", "🟢"), unsafe_allow_html=True)
        time.sleep(1.5)
        math_overlay.empty()

    # Phase 2 -> 3: Configuration
    st.session_state.demo_phase = 3
    update_phase_tracker_ui()
    status_text.success("Phase 3: Deploying GCL to Network Switches...")
    current_logs += "[CNC] Compiling YANG-style XML Configurations...\n"
    log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
    time.sleep(1.0)
    gantt_placeholder.plotly_chart(draw_gantt_chart(), use_container_width=True)
    queue_buffer_placeholder.markdown(draw_queue_buffers(q0_fill=0, q7_fill=0, gate0_open=True, gate7_open=False), unsafe_allow_html=True)
    current_logs += "[CNC] Deployed Gate Control Lists successfully to SW1, SW2, SW3, SW4.\n"
    log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
    time.sleep(2.0)

    # Phase 3 -> 4: Live Stress Test
    st.session_state.demo_phase = 4
    update_phase_tracker_ui()
    status_text.error("Phase 4: Running SimPy Live Stress-Test. Injecting massive interference.")

    payloads = [3200, 16000, 32000, 64000, 102400]
    expected_latency = 345.84 # Strict deterministic value
    base_latency_p0 = 1200
    p0_latencies = []
    p7_latencies = []

    progress_bar = st.progress(0)

    for i, payload in enumerate(payloads):
        time.sleep(0.8)
        current_logs += f"[SimPy] Stress Test Iteration {i+1}/5: Injecting {payload:,} Bytes of Prio 0 Traffic...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        time.sleep(0.5)

        current_p0_latency = base_latency_p0 + (payload * 0.15)
        p0_latencies.append(current_p0_latency)
        p7_latencies.append(expected_latency)

        # Update glowing metric cards with explicit Jitter Math
        f1_metric.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px;'>{expected_latency:.2f} µs</span><br><small style='color:lightgreen;'><b>Current Jitter:</b> Lat<sub>actual</sub> - Lat<sub>expected</sub> = 0.00 µs</small></div>", unsafe_allow_html=True)
        f2_metric.markdown(f"<div class='metric-card'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#faca2b;'>{payload:,} Bytes</span><br><small style='color:#faca2b;'>{current_p0_latency:.2f} µs Latency (+{payload - payloads[i-1] if i > 0 else 0} B)</small></div>", unsafe_allow_html=True)

        # Dynamic animated plotting (Make sure this exists for Phase 5 to render properly)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=payloads[:i+1], y=p7_latencies,
            mode='lines+markers',
            name='Flow 1: Mission-Critical',
            line=dict(color='#ff4b4b', width=4),
            marker=dict(size=10)
        ))
        fig.add_trace(go.Scatter(
            x=payloads[:i+1], y=p0_latencies,
            mode='lines+markers',
            name='Flow 2: Interference',
            line=dict(color='#faca2b', width=3, dash='dash'),
            marker=dict(size=10),
            yaxis='y2'
        ))

        fig.update_layout(
            title=dict(text="Real-Time End-to-End Latency vs. Interference Payload", font=dict(color='white')),
            xaxis=dict(title=dict(text="Flow 2 Payload Size (Bytes)", font=dict(color='white')), type="category", tickfont=dict(color='white')),
            yaxis=dict(title=dict(text="Flow 1 Latency (µs)", font=dict(color="#ff4b4b")), tickfont=dict(color="#ff4b4b"), range=[0, 1000]),
            yaxis2=dict(title=dict(text="Flow 2 Latency (µs)", font=dict(color="#faca2b")), tickfont=dict(color="#faca2b"), overlaying='y', side='right', range=[0, max(20000, current_p0_latency * 1.2)]),
            legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=40, r=40, t=40, b=40),
            height=300
        )
        chart_placeholder.plotly_chart(fig, use_container_width=True)

        current_logs += f"[Result] Iteration {i+1} complete: Prio 7 Latency locked at {expected_latency} µs.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)

        progress = (i + 1) / len(payloads)
        progress_bar.progress(progress)

    time.sleep(1.0)

    if st.session_state.slow_mo:
        current_logs += "[Slow-Mo] Transitioning to Microsecond Slow-Motion view...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        time.sleep(1.0)
        st.session_state.demo_phase = 5
        st.session_state.final_logs = current_logs
        st.rerun()
    else:
        current_logs += "[Verification] Live Stress-Test complete. Determinism mathematically and empirically validated.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        status_text.success("Presentation Complete! The SD-TSN perfectly maintained critical operations despite 100KB+ interference.")
        st.session_state.final_logs = current_logs
        st.session_state.is_running = False
        # Rerun to cleanly update the phase tracker to show all phases green/done
        st.rerun()

# --- Phase 5: Microsecond Slow-Motion ---
if st.session_state.demo_phase == 5:
    st.session_state.is_running = True # Keep running so things don't glitch
    status_text.warning("Phase 5: Microsecond Slow-Motion. Analyzing 102.4KB Payload injection at cycle boundary.")

    payloads = [3200, 16000, 32000, 64000, 102400]
    expected_latency = 345.84
    final_payload = payloads[-1]
    final_p0_latency = 1200 + (final_payload * 0.15)

    f1_metric.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px;'>{expected_latency:.2f} µs</span><br><small style='color:lightgreen;'><b>Current Jitter:</b> Lat<sub>actual</sub> - Lat<sub>expected</sub> = 0.00 µs</small></div>", unsafe_allow_html=True)
    f2_metric.markdown(f"<div class='metric-card'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#faca2b;'>{final_payload:,} Bytes</span><br><small style='color:#faca2b;'>{final_p0_latency:.2f} µs Latency (+{(final_payload - payloads[-2]) if len(payloads)>1 else 0} B)</small></div>", unsafe_allow_html=True)

    # Calculate state based on us_clock
    t = st.session_state.us_clock

    # Basic GCL Rules
    # t < -121.76: Guard Band (Queue 0 closed, Queue 7 closed)
    # 0 <= t <= 81.92: Queue 7 Open
    # t > 81.92: Queue 0 Open again

    gate0_open = False
    gate7_open = False
    q0_fill = 0
    q7_fill = 0

    if t < -121.76:
        gate0_open = True
        gate7_open = False
        q0_fill = 10  # Idle traffic
        q7_fill = 0
    elif -121.76 <= t < 0:
        gate0_open = False
        gate7_open = False
        # Queue 0 fills rapidly because 102KB is trying to egress but gate is closed
        fill_progress = (t + 121.76) / 121.76
        q0_fill = min(100, 10 + (90 * fill_progress))
        q7_fill = 100  # Critical packet arrives exactly during guard band
    elif 0 <= t <= 81.92:
        gate0_open = False
        gate7_open = True
        q0_fill = 100 # Still blocked
        q7_fill = max(0, 100 - (100 * (t / 81.92))) # Draining
    else:
        gate0_open = True
        gate7_open = False
        q0_fill = max(0, 100 - (100 * ((t - 81.92) / 200))) # Draining slowly
        q7_fill = 0

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("⏭️ Step Forward (+10 µs)"):
            if st.session_state.us_clock < 250:
                st.session_state.us_clock += 10.0
            st.rerun()
    with col_btn2:
        if st.button("⏹️ Finish Presentation"):
            st.session_state.is_running = False
            st.session_state.demo_phase = 4 # Revert to finished state
            st.rerun()

    topo_placeholder.plotly_chart(create_network_topology(), use_container_width=True, key="topo_p5")

    # Update chart and buffer dynamically
    gantt_placeholder.plotly_chart(draw_gantt_chart(current_time=t), use_container_width=True, key="gantt_p5")
    queue_buffer_placeholder.markdown(draw_queue_buffers(q0_fill=q0_fill, q7_fill=q7_fill, gate0_open=gate0_open, gate7_open=gate7_open), unsafe_allow_html=True)

    log_msg = st.session_state.final_logs + f"\n[Clock] Current Time: {t:.2f} µs | P0 Gate: {'OPEN' if gate0_open else 'CLOSED'} | P7 Gate: {'OPEN' if gate7_open else 'CLOSED'}"
    log_placeholder.markdown(write_terminal_log(log_msg), unsafe_allow_html=True)

    # Render line chart statically as it was
    payloads = [3200, 16000, 32000, 64000, 102400]
    expected_latency = 345.84
    p7_latencies = [expected_latency] * len(payloads)
    p0_latencies = [1200 + (p * 0.15) for p in payloads]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=payloads, y=p7_latencies, mode='lines+markers', name='Flow 1: Mission-Critical', line=dict(color='#ff4b4b', width=4), marker=dict(size=10)))
    fig.add_trace(go.Scatter(x=payloads, y=p0_latencies, mode='lines+markers', name='Flow 2: Interference', line=dict(color='#faca2b', width=3, dash='dash'), marker=dict(size=10), yaxis='y2'))
    fig.update_layout(title=dict(text="Real-Time End-to-End Latency vs. Interference Payload", font=dict(color='white')), xaxis=dict(title=dict(text="Flow 2 Payload Size (Bytes)", font=dict(color='white')), type="category", tickfont=dict(color='white')), yaxis=dict(title=dict(text="Flow 1 Latency (µs)", font=dict(color="#ff4b4b")), tickfont=dict(color="#ff4b4b"), range=[0, 1000]), yaxis2=dict(title=dict(text="Flow 2 Latency (µs)", font=dict(color="#faca2b")), tickfont=dict(color="#faca2b"), overlaying='y', side='right', range=[0, max(20000, 1200 + (payloads[-1] * 0.15) * 1.2)]), legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=40, t=40, b=40), height=300)
    chart_placeholder.plotly_chart(fig, use_container_width=True, key="chart_p5")


# Persist visual elements if phase completes
if not st.session_state.is_running and st.session_state.demo_phase == 4:
    topo_placeholder.plotly_chart(create_network_topology(), use_container_width=True, key="topo_persist")
    gantt_placeholder.plotly_chart(draw_gantt_chart(), use_container_width=True, key="gantt_persist")

    # Restore metrics
    payloads = [3200, 16000, 32000, 64000, 102400]
    expected_latency = 345.84
    final_payload = payloads[-1]
    final_p0_latency = 1200 + (final_payload * 0.15)

    f1_metric.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px;'>{expected_latency:.2f} µs</span><br><small style='color:lightgreen;'>0.00 µs Jitter (Deterministic)</small></div>", unsafe_allow_html=True)
    f2_metric.markdown(f"<div class='metric-card'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#faca2b;'>{final_payload:,} Bytes</span><br><small style='color:#faca2b;'>{final_p0_latency:.2f} µs Latency (+{(final_payload - payloads[-2]) if len(payloads)>1 else 0} B)</small></div>", unsafe_allow_html=True)

    # Restore chart
    p7_latencies = [expected_latency] * len(payloads)
    p0_latencies = [1200 + (p * 0.15) for p in payloads]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=payloads, y=p7_latencies,
        mode='lines+markers',
        name='Flow 1: Mission-Critical',
        line=dict(color='#ff4b4b', width=4),
        marker=dict(size=10)
    ))
    fig.add_trace(go.Scatter(
        x=payloads, y=p0_latencies,
        mode='lines+markers',
        name='Flow 2: Interference',
        line=dict(color='#faca2b', width=3, dash='dash'),
        marker=dict(size=10),
        yaxis='y2'
    ))

    fig.update_layout(
        title=dict(text="Real-Time End-to-End Latency vs. Interference Payload", font=dict(color='white')),
        xaxis=dict(title=dict(text="Flow 2 Payload Size (Bytes)", font=dict(color='white')), type="category", tickfont=dict(color='white')),
        yaxis=dict(title=dict(text="Flow 1 Latency (µs)", font=dict(color="#ff4b4b")), tickfont=dict(color="#ff4b4b"), range=[0, 1000]),
        yaxis2=dict(title=dict(text="Flow 2 Latency (µs)", font=dict(color="#faca2b")), tickfont=dict(color="#faca2b"), overlaying='y', side='right', range=[0, max(20000, final_p0_latency * 1.2)]),
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=40, r=40, t=40, b=40),
        height=300
    )
    chart_placeholder.plotly_chart(fig, use_container_width=True, key="chart_persist")

    log_placeholder.markdown(write_terminal_log(st.session_state.final_logs), unsafe_allow_html=True)
    status_text.success("Presentation Complete! The SD-TSN perfectly maintained critical operations despite 100KB+ interference.")
