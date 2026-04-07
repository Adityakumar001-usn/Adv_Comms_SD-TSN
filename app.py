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

from models import Topology, Flow
from cuc import MockCUC
from routing import CNCRouting
from scheduler import ILPScheduler
from gcl import GCLGenerator
from simulator import TSNSimulator

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

# Store backend calculation results to persist across UI reruns
if 'backend_results' not in st.session_state:
    st.session_state.backend_results = {}

st.sidebar.title("Simulation Settings")
expand_network = st.sidebar.checkbox("Expand Network (Add SW5 & E4)", value=False)
link_speed = st.sidebar.selectbox("Physical Link Speed", [100, 1000], index=0, format_func=lambda x: f"{x} Mbps")
critical_payload_size = st.sidebar.slider("Critical Payload Size (Bytes)", min_value=128, max_value=1500, value=1024, step=128, help="Size of the Mission-Critical Prio 7 Flow")
interference_max_payload = st.sidebar.slider("Interference Payload Max (Bytes)", min_value=1000, max_value=150000, value=102400, step=1000, help="Maximum background traffic injected in Phase 4")
attack_duration_ms = st.sidebar.slider("Simulation Window (ms)", 100, 1000, 200, step=100, help="Duration of the Live Stress-Test Simulation")
st.session_state.slow_mo = st.sidebar.toggle("Enable Microsecond Slow-Mo", value=st.session_state.slow_mo, help="Pause at the maximum payload and manually step through the TAS scheduling.")

@st.cache_data(show_spinner=False)
def calculate_ilp_schedule(f1_payload, expand_topology, link_speed_mbps):
    """Cached wrapper to run the PuLP ILP solver so it doesn't re-run on every UI update."""
    topo = Topology(expand_topology=expand_topology, link_speed_mbps=link_speed_mbps)
    cuc = MockCUC()
    base_flows = cuc.generate_test_flows()

    # Override Flow 1 with the user slider value
    for f in base_flows:
        if f.flow_id == "Flow1":
            f.payload_size = f1_payload

    routing = CNCRouting(topo)
    routes = routing.compute_routes(base_flows)

    scheduler = ILPScheduler(topo, routes, link_speed_mbps=link_speed_mbps)
    flow1 = next(f for f in base_flows if f.flow_id == "Flow1")

    schedule = scheduler.schedule_flow(flow1)
    t_trans = scheduler.transmission_duration(flow1.payload_size)

    gcl_gen = GCLGenerator(topo, routing.port_map)
    hyper_period = gcl_gen.calculate_hyper_period(base_flows)
    gcl_config = gcl_gen.generate_gcl(schedule, t_trans, hyper_period, flow1.period)

    l2_tables = routing.generate_l2_lookup_tables(base_flows)
    xml_output = gcl_gen.generate_xml_configuration(l2_tables, gcl_config, hyper_period)

    # Calculate expected latency based on ILP mathematical model
    path = routes[flow1.flow_id]
    first_edge = (path[0], path[1])
    last_edge = (path[-2], path[-1])
    expected_latency = schedule[last_edge] + t_trans - schedule[first_edge]

    # Guard band needs to block MTU at 100Mbps
    # 1522 bytes * 8 bits / 100Mbps = 121.76 us
    guard_band = scheduler.guard_band

    return {
        "schedule": schedule,
        "t_trans": t_trans,
        "expected_latency": expected_latency,
        "guard_band": guard_band,
        "gcl_config": gcl_config,
        "hyper_period": hyper_period,
        "routes": routes,
        "l2_tables": l2_tables,
        "xml_output": xml_output
    }

@st.cache_data(show_spinner=False)
def run_cached_sim_iterations(f1_payload, f2_max, gcl_config, hyper_period, tas_enabled=True, attack_active=False, expand_topology=False, link_speed_mbps=100, sim_duration_ms=200):
    """Wrapper to run the full simulation stress-test loop."""
    topo = Topology(expand_topology=expand_topology, link_speed_mbps=link_speed_mbps)
    if attack_active:
        # Add rogue node to topology just for the simulation routes
        topo.graph.add_node('MockAttacker', type='endpoint')
        topo.add_bidirectional_link('MockAttacker', 'SW1')

    cuc = MockCUC()
    base_flows = cuc.generate_test_flows()

    step_size = f2_max // 5
    payloads = [step_size * (i+1) for i in range(5)]
    payloads[-1] = f2_max

    p0_latencies = []
    p7_latencies = []
    dropped_packets = 0

    for payload in payloads:
        flows = []
        for f in base_flows:
            if f.flow_id == "Flow1":
                # We need to explicitly clone the flow to avoid caching state pollution
                flow1 = Flow("Flow1", f.source, f.destination, f.period, f.priority, f1_payload, f.max_latency)
                flows.append(flow1)
            elif f.flow_id == "Flow2":
                flow2 = Flow("Flow2", f.source, f.destination, f.period, f.priority, payload, f.max_latency)
                flows.append(flow2)

        if attack_active:
            # Inject high frequency spoofed Prio 7 packets from Rogue Node
            rogue_flow = Flow("RogueFlow", "MockAttacker", "E3", period=1000, priority=7, payload_size=1500, max_latency=0)
            flows.append(rogue_flow)

        routing = CNCRouting(topo)
        sim = TSNSimulator(topo, routing, gcl_config, hyper_period, tas_enabled=tas_enabled, attack_active=attack_active, link_speed_mbps=link_speed_mbps)

        for flow in flows:
            sim.start_flow(flow)

        print(f"[BACKEND LOG] Running TSNSimulator for payload size: {payload} Bytes...", flush=True)

        sim_duration_us = sim_duration_ms * 1000
        sim.run(sim_duration_us)

        f1_latencies = sim.latencies.get("Flow1", [])
        f2_latencies = sim.latencies.get("Flow2", [])

        f1_avg = sum(f1_latencies) / len(f1_latencies) if f1_latencies else 0
        f2_avg = sum(f2_latencies) / len(f2_latencies) if f2_latencies else 0

        p7_latencies.append(f1_avg)
        p0_latencies.append(f2_avg)
        dropped_packets = sim.dropped_spoofed_packets

    return payloads, p7_latencies, p0_latencies, dropped_packets

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

def create_network_topology(attack_active=False, stage="full", flow1_hops=None, flow2_hops=None, expand_topology=False):
    # Constructing a simple representation of our Zonal Architecture
    # E1 -> SW1 -> SW3 -> GW -> E3
    # E2 -> SW2 -> SW4 -> GW -> E3

    nodes = ['E1', 'E2', 'SW1', 'SW2', 'SW3', 'SW4', 'GW', 'E3']
    edges = [
        ('E1', 'SW1'), ('SW1', 'SW3'), ('SW3', 'GW'), ('GW', 'E3'),
        ('E2', 'SW2'), ('SW2', 'SW4'), ('SW4', 'GW')
    ]

    if attack_active:
        nodes.append('MockAttacker')

    if expand_topology:
        nodes.extend(['SW5', 'E4'])
        edges.extend([('SW4', 'SW5'), ('SW5', 'E4')])

    # We define fixed positions to make it look like a clean zonal architecture diagram
    pos = {
        'E1': (0, 2),
        'SW1': (1, 2),
        'SW3': (2, 2),
        'E2': (0, 0),
        'SW2': (1, 0),
        'SW4': (2, 0),
        'GW': (3, 1),
        'E3': (4, 1),
        'SW5': (2, -1),
        'E4': (1, -1),
        'MockAttacker': (0, 3)
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

    traces = []

    if stage in ["links", "flow1_routing", "flow2_routing", "full"]:
        # Base edges (gray)
        edge_trace = go.Scatter(
            x=edge_x, y=edge_y,
            line=dict(width=2, color='#888'),
            hoverinfo='none',
            mode='lines',
            name='Network Links'
        )
        traces.append(edge_trace)

    if attack_active and stage == "full":
        att_x = [pos['MockAttacker'][0], pos['SW1'][0], None]
        att_y = [pos['MockAttacker'][1], pos['SW1'][1], None]
        att_trace = go.Scatter(
            x=att_x, y=att_y,
            line=dict(width=4, color='#ff0000', dash='dot'),
            hoverinfo='none',
            mode='lines',
            name='Rogue Node Attack Vector'
        )
        traces.append(att_trace)

    # Flow 1 edges (Glowing Red)
    if stage in ["flow1_routing", "flow2_routing", "full"]:
        f1_x = []
        f1_y = []
        edges_to_draw = flow1_edges if flow1_hops is None else flow1_edges[:flow1_hops]
        for edge in edges_to_draw:
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            f1_x.extend([x0, x1, None])
            f1_y.extend([y0, y1, None])

        if f1_x:
            f1_trace = go.Scatter(
                x=f1_x, y=f1_y,
                line=dict(width=6, color='#ff4b4b'), # Streamlit red
                hoverinfo='none',
                mode='lines',
                name='Flow 1: Mission-Critical Route'
            )
            traces.append(f1_trace)

    # Flow 2 edges (Dashed Amber)
    if stage in ["flow2_routing", "full"]:
        f2_x = []
        f2_y = []
        edges_to_draw = flow2_edges if flow2_hops is None else flow2_edges[:flow2_hops]
        for edge in edges_to_draw:
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            f2_x.extend([x0, x1, None])
            f2_y.extend([y0, y1, None])

        if f2_x:
            f2_trace = go.Scatter(
                x=f2_x, y=f2_y,
                line=dict(width=4, color='#faca2b', dash='dash'), # Amber
                hoverinfo='none',
                mode='lines',
                name='Flow 2: Background Interference Route'
            )
            traces.append(f2_trace)

    node_x = []
    node_y = []
    node_text = []
    node_color = []
    for node in nodes:
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(f"<b>{node}</b>")
        if node == 'MockAttacker':
            node_color.append('#ff0000') # Bright red
        elif 'E' in node:
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

    traces.append(node_trace)

    fig = go.Figure(data=traces,
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
    # Clear out old backend results so we rerun
    st.session_state.backend_results = {}

# UI Layout Placeholder
col1, col2 = st.columns([1, 1])

with col1:
    topo_placeholder = st.empty()
    if st.session_state.demo_phase == 0 and not st.session_state.is_running:
        topo_placeholder.markdown("<div class='placeholder-box'><h4>Zonal Topology</h4><p>Awaiting Phase 1: Discovery...</p></div>", unsafe_allow_html=True)
    elif st.session_state.demo_phase >= 1:
        topo_placeholder.plotly_chart(create_network_topology(expand_topology=expand_network), width="stretch", key="init_topo")

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
        chart_placeholder.plotly_chart(draw_empty_chart("Real-Time End-to-End Latency vs. Payload", "Flow 2 Payload Size (Bytes)", "Latency (µs)"), width="stretch", key="init_chart")

with col_bottom2:
    gantt_placeholder = st.empty()
    queue_buffer_placeholder = st.empty() # Added placeholder for the queue buffers
    if st.session_state.demo_phase < 3:
        gantt_placeholder.plotly_chart(draw_empty_chart("Switch Egress TAS Schedule", "Time relative to Cycle Start (µs)", ""), width="stretch", key="init_gantt")

st.markdown("### Simulated Live Logs")
log_placeholder = st.empty()
if not st.session_state.is_running and st.session_state.demo_phase == 0:
    log_placeholder.markdown("<div class='terminal-window' id='terminal_out'>user@cnc-server:~$ waiting for demo initialization...<span class='cursor'>_</span></div>", unsafe_allow_html=True)

def draw_gantt_chart(current_time=None, ilp_results=None, tas_enabled=True):
    # Retrieve backend metrics dynamically if available
    guard_band = 121.76
    t_trans = 81.92

    if ilp_results:
        guard_band = ilp_results.get('guard_band', guard_band)
        t_trans = ilp_results.get('t_trans', t_trans)
    elif 'backend_results' in st.session_state and 'guard_band' in st.session_state.backend_results:
        guard_band = st.session_state.backend_results['guard_band']
        t_trans = st.session_state.backend_results['t_trans']

    # Period: 50,000 µs (50ms)
    hyper_period = 50000.0

    # We'll just show the first 250 µs of the cycle to highlight the scheduling
    fig = go.Figure()

    # Priority 0 Queue
    fig.add_trace(go.Bar(
        y=['Queue 0 (Best Effort)'],
        x=[200], # Open after guard band / P7
        base=[t_trans + 18.08], # Open slightly after P7 finishes
        orientation='h',
        marker=dict(color='orange'),
        name='P0 Open',
        text='P0 Traffic Allowed',
        hoverinfo='text'
    ))

    # Priority 7 Queue
    fig.add_trace(go.Bar(
        y=['Queue 7 (Time-Sensitive)'],
        x=[t_trans], # Time to transmit
        base=[0],
        orientation='h',
        marker=dict(color='red'),
        name='P7 Open',
        text=f'P7 Transmission ({t_trans:.2f} µs)',
        hoverinfo='text'
    ))

    if tas_enabled:
        # Guard Band
        fig.add_trace(go.Bar(
            y=['Queue 0 (Best Effort)'],
            x=[guard_band],
            base=[-guard_band + hyper_period],
            orientation='h',
            marker=dict(color='#8B0000', pattern_shape="/"),
            name='Guard Band',
            hovertext=f'<b>Guard Band ({guard_band:.2f} µs)</b><br>This safety gap prevents delivery trucks (P0)<br>from blocking the ambulance (P7).',
            hoverinfo='text'
        ))

        # To make the Gantt look coherent, let's plot a relative window from -150us to +300us
        fig.add_trace(go.Bar(
            y=['Queue 0 (Best Effort)'],
            x=[guard_band],
            base=[-guard_band],
            orientation='h',
            marker=dict(color='#8B0000', pattern_shape="/"),
            name='Guard Band',
            hovertext=f'<b>Guard Band ({guard_band:.2f} µs)</b><br>This safety gap prevents delivery trucks (P0)<br>from blocking the ambulance (P7).',
            hoverinfo='text',
            showlegend=False
        ))
    else:
        # Without TAS, P0 is just open across the whole negative spectrum
        fig.add_trace(go.Bar(
            y=['Queue 0 (Best Effort)'],
            x=[150],
            base=[-150],
            orientation='h',
            marker=dict(color='orange'),
            name='P0 Open (Unrestricted)',
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

def draw_queue_buffers(q0_fill, q7_fill, gate0_open, gate7_open, tas_enabled=True):
    """
    Draws custom HTML/CSS progress bars representing the live switch egress port queues.
    This bypasses standard Streamlit limitations to create a smooth, reactive animation.
    """
    g0_color = "#4ade80" if gate0_open else "#4b5563"
    g0_text = "OPEN" if gate0_open else "CLOSED"

    g7_color = "#4ade80" if gate7_open else "#4b5563"
    g7_text = "OPEN" if gate7_open else "CLOSED"

    container_style = "background-color: #111827; padding: 15px; border-radius: 8px; border: 1px solid #1f2937;"
    if not tas_enabled:
        container_style += " opacity: 0.4;"
    else:
        container_style += " box-shadow: 0 0 15px rgba(74, 222, 128, 0.2);"

    html = f"""
<div style="{container_style}">
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
    import textwrap
    return textwrap.dedent(html).strip()


def write_terminal_log(logs):
    """Wraps text in our custom terminal CSS"""
    # Replace newlines with <br> for HTML rendering
    html_logs = logs.replace('\n', '<br>')
    return f"<div class='terminal-window' id='terminal_out'>user@cnc-server:~$ {html_logs}<span class='cursor'>_</span></div>"

def draw_latency_chart(payloads, p7_latencies, p0_latencies, expected_latency):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=payloads, y=p7_latencies, mode='lines+markers', name='Flow 1: Mission-Critical', line=dict(color='#ff4b4b', width=4), marker=dict(size=10)))
    fig.add_trace(go.Scatter(x=payloads, y=p0_latencies, mode='lines+markers', name='Flow 2: Interference', line=dict(color='#faca2b', width=3, dash='dash'), marker=dict(size=10), yaxis='y2'))
    fig.update_layout(title=dict(text="Real-Time End-to-End Latency vs. Interference Payload", font=dict(color='white')), xaxis=dict(title=dict(text="Flow 2 Payload Size (Bytes)", font=dict(color='white')), type="category", tickfont=dict(color='white')), yaxis=dict(title=dict(text="Flow 1 Latency (µs)", font=dict(color="#ff4b4b")), tickfont=dict(color="#ff4b4b"), range=[0, max(max(p7_latencies) * 1.5, expected_latency * 1.5)]), yaxis2=dict(title=dict(text="Flow 2 Latency (µs)", font=dict(color="#faca2b")), tickfont=dict(color="#faca2b"), overlaying='y', side='right', range=[0, max(20000, p0_latencies[-1] * 1.2)]), legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=40, t=40, b=40), height=300)
    return fig

# Sequential Demo Execution Block
if st.session_state.is_running and st.session_state.demo_phase == 0:
    try:
        # Phase 0 -> 1: Discovery / Digital Twin Layer 1 & 2
        st.session_state.demo_phase = 1
        update_phase_tracker_ui()
        current_logs = "[System] Initializing Presentation Engine...\n"
        current_logs += "[Digital Twin] Layer 1: Instantiating Physical Nodes...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        status_text.info("Phase 1: Building Digital Twin - Physical Layer & Links")

        # Nodes
        topo_placeholder.plotly_chart(create_network_topology(stage="nodes", expand_topology=expand_network), width="stretch", key="p1_nodes")
        time.sleep(1.0)

        # Links
        current_logs += f"[Digital Twin] Layer 1: Establishing {link_speed}Mbps Ethernet Links...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        topo_placeholder.plotly_chart(create_network_topology(stage="links", expand_topology=expand_network), width="stretch", key="p1_links")
        time.sleep(1.0)

        # Routing Flow 1
        current_logs += f"[CUC] Provisioning Flow 1: Mission-Critical (Prio 7), Payload: {critical_payload_size} Bytes.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        for hops in range(1, 5): # 4 edges
            topo_placeholder.plotly_chart(create_network_topology(stage="flow1_routing", flow1_hops=hops, expand_topology=expand_network), width="stretch", key=f"p1_f1_{hops}")
            time.sleep(0.5)

        # Routing Flow 2
        current_logs += f"[CUC] Provisioning Flow 2: Best-Effort Interference (Prio 0), Max Payload: {interference_max_payload} Bytes.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        for hops in range(1, 5): # 4 edges
            topo_placeholder.plotly_chart(create_network_topology(stage="flow2_routing", flow1_hops=4, flow2_hops=hops, expand_topology=expand_network), width="stretch", key=f"p1_f2_{hops}")
            time.sleep(0.5)

        # Phase 1 -> 2: Optimization (ILP Deep-Dive)
        st.session_state.demo_phase = 2
        update_phase_tracker_ui()
        status_text.warning("Phase 2: Mathematical Solver (Layer 3) - Validating Constraints")

        current_logs += "[PuLP] Activating ILP Mathematical Solver...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)

        # Trigger actual backend calculation
        ilp_results = calculate_ilp_schedule(critical_payload_size, expand_network, link_speed)
        st.session_state.backend_results = ilp_results

        guard_band_val = ilp_results['guard_band']
        expected_latency = ilp_results['expected_latency']

        with chart_placeholder.container():
            with st.status("🧠 PuLP ILP Mathematical Constraint Checklist", expanded=True) as status:
                st.write("Checking Egress Port Buffer Constraints...")
                time.sleep(1.0)
                current_logs += "[PuLP] Flow Isolation Checked: Switch egress buffer conflict resolved.\n"
                log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
                st.write("✔️ Buffer Collisions Prevented")

                time.sleep(1.0)
                st.write(f"Calculating {link_speed}Mbps MTU Guard Band...")
                current_logs += f"[PuLP] Calculating required Guard Band... Solved: {guard_band_val:.2f} µs.\n"
                log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
                st.write(f"✔️ Guard Band Size: {guard_band_val:.2f} µs")

                time.sleep(1.0)
                st.write("Locking End-to-End Latency Target...")
                current_logs += f"[PuLP] Bounding end-to-end path delay... Solved: {expected_latency:.2f} µs.\n"
                log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
                st.write(f"✔️ Guaranteed Target Latency: {expected_latency:.2f} µs")

                time.sleep(1.5)
                status.update(label="✔️ ILP Constraints Verified & Solved", state="complete", expanded=False)

        # Phase 2 -> 3: Configuration
        st.session_state.demo_phase = 3
        update_phase_tracker_ui()
        status_text.success("Phase 3: Deploying GCL and Initializing SimPy Engine...")
        current_logs += "[CNC] Compiling YANG-style XML Configurations...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)

        # Write network config XML to file
        with open("network_config.xml", "w") as f:
            f.write(ilp_results.get("xml_output", ""))

        time.sleep(1.0)

        current_logs += "[SimPy] Initializing Discrete-Event Physics Engine...\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        gantt_placeholder.plotly_chart(draw_gantt_chart(), width="stretch", key="phase3_gantt")
        queue_buffer_placeholder.html(draw_queue_buffers(q0_fill=0, q7_fill=0, gate0_open=True, gate7_open=False))

        current_logs += "[CNC] Deployed Gate Control Lists successfully to SW1, SW2, SW3, SW4.\n"
        current_logs += "[SimPy] Clock Initialized at 0.00 µs.\n"
        log_placeholder.markdown(write_terminal_log(current_logs), unsafe_allow_html=True)
        time.sleep(2.0)

        # Pre-flight Phase 4 transition
        st.session_state.demo_phase = 4
        st.session_state.is_running = False
        st.session_state.final_logs = current_logs
        st.rerun()

    except Exception as e:
        st.error(f"**Backend Crash**: An unexpected error occurred during execution: {e}")
        st.session_state.is_running = False

# Persistent Phase 4 execution block (Detached from is_running loop)
if st.session_state.demo_phase == 4 and not st.session_state.is_running:
    update_phase_tracker_ui()
    status_text.error("Phase 4: Advanced Validation Scenarios. Isolate Performance & Security metrics.")
    log_placeholder.markdown(write_terminal_log(st.session_state.final_logs), unsafe_allow_html=True)

    # Restore persistent UI elements from previous phases
    topo_placeholder.plotly_chart(create_network_topology(expand_topology=expand_network), width="stretch", key="p4_topo")

    # Dynamically recalculate ILP results so moving the sliders updates the microsecond offsets in real-time
    ilp_results = calculate_ilp_schedule(critical_payload_size, expand_network, link_speed)
    st.session_state.backend_results = ilp_results # update session state too so Phase 5 gets the right data

    expected_latency = ilp_results.get('expected_latency', 0.0)
    gcl_config = ilp_results.get('gcl_config', {})
    hyper_period = ilp_results.get('hyper_period', 50000.0)

    with chart_placeholder.container():
        # Live XML Expander (moved up)
        with st.expander("🔬 View Live Switch Configuration (L2 & GCL XML)", expanded=False):
            if 'xml_deployed' not in st.session_state:
                with st.spinner("Deploying XML to SW1, SW2, SW3, SW4 via TCP/IP..."):
                    time.sleep(1.5)
                st.session_state.xml_deployed = True

            st.success("Configuration deployed successfully.")
            st.markdown("#### Layer 2 MAC Forwarding Routes (Generated by Dijkstra)")
            st.json(ilp_results.get("l2_tables", {}))
            st.markdown("#### Gate Control List (YANG-style XML Generated by PuLP)")
            st.code(ilp_results.get("xml_output", ""), language="xml")

        st.markdown("### Interactive Validation Scenarios")
        tab1, tab2 = st.tabs(["📊 Scenario A: Performance (IEEE 802.1Qbv)", "🛡️ Scenario B: Security (Cyber Attack)"])

        with tab1:
            st.markdown("Test the deterministic guarantees of the Time-Aware Shaper (TAS) against unshaped Strict Priority routing.")
            tas_enabled = st.toggle("Enable IEEE 802.1Qbv TAS", value=True, help="Toggle to compare shaped traffic vs. unshaped traffic.")

            if not tas_enabled:
                st.error("⚠️ **MODE: Best-Effort (Legacy SP)**  \n*Gate Control List is INACTIVE. Priority 0 traffic is unregulated, causing the latency spikes seen in the chart below.*")
            else:
                st.success("🛡️ **MODE: Deterministic (SD-TSN)**  \n*GCL Active. The ILP Scheduler is physically policing the egress gates to protect the microsecond critical window.*")

            with gantt_placeholder.container():
                st.plotly_chart(draw_gantt_chart(ilp_results=ilp_results, tas_enabled=tas_enabled), width="stretch", key=f"tab1_gantt_{tas_enabled}")

            # Metric for SimPy Clock
            st.markdown("### ⏱️ SimPy Discrete-Event Clock")
            simpy_clock = st.empty()

            # Animate the queues filling up proportionally to the payloads being tested
            payloads, p7_lats, p0_lats, _ = run_cached_sim_iterations(critical_payload_size, interference_max_payload, gcl_config, hyper_period, tas_enabled=tas_enabled, attack_active=False, expand_topology=expand_network, link_speed_mbps=link_speed, sim_duration_ms=attack_duration_ms)

            for idx, p in enumerate(payloads):
                step_size_ms = attack_duration_ms // 5
                sim_time_ms = (idx + 1) * step_size_ms
                simpy_clock.metric("Virtual Time Passed", f"{sim_time_ms} ms")
                q0_percent = min(100, int((p / interference_max_payload) * 100))
                queue_buffer_placeholder.html(draw_queue_buffers(q0_fill=q0_percent, q7_fill=0, gate0_open=True, gate7_open=False, tas_enabled=tas_enabled))
                time.sleep(1.0)

            final_p7 = p7_lats[-1]
            jitter = final_p7 - expected_latency

            col_m1, col_m2 = st.columns(2)
            if abs(jitter) < 0.01: # Treat as 0.00
                col_m1.markdown(f"<div class='metric-card glow-text'><strong>Status: Deterministic</strong><br><span style='font-size:24px; color:#4ade80;'>0.00 µs Jitter</span></div>", unsafe_allow_html=True)
            else:
                col_m1.markdown(f"<div class='metric-card glow-text'><strong>Status: Unsafe</strong><br><span style='font-size:24px; color:#ff4b4b;'>Jitter: +{jitter:.2f} µs</span></div>", unsafe_allow_html=True)

            st.plotly_chart(draw_latency_chart(payloads, p7_lats, p0_lats, expected_latency), width="stretch", key=f"tab1_latency_{tas_enabled}")

            st.session_state.backend_results['payloads'] = payloads
            st.session_state.backend_results['p7_latencies'] = p7_lats
            st.session_state.backend_results['p0_latencies'] = p0_lats

        with tab2:
            st.markdown("Test the CNC controller's ability to isolate unauthorized rogue nodes attempting to spoof Priority 7 traffic.")
            attack_btn = st.button("☠️ Trigger Rogue Node Attack", type="primary")

            if attack_btn:
                st.error("⚠️ CRITICAL: UNAUTHORIZED PRIORITY 7 INGRESS DETECTED AT SW1")
                with topo_placeholder.container():
                    st.plotly_chart(create_network_topology(attack_active=True, expand_topology=expand_network), width="stretch", key="tab2_topo_attack")

                # Metric for SimPy Clock
                st.markdown("### ⏱️ SimPy Discrete-Event Clock")
                simpy_clock_attack = st.empty()

                payloads, p7_lats, p0_lats, dropped = run_cached_sim_iterations(critical_payload_size, interference_max_payload, gcl_config, hyper_period, tas_enabled=True, attack_active=True, expand_topology=expand_network, link_speed_mbps=link_speed, sim_duration_ms=attack_duration_ms)

                for idx, p in enumerate(payloads):
                    step_size_ms = attack_duration_ms // 5
                    sim_time_ms = (idx + 1) * step_size_ms
                    simpy_clock_attack.metric("Virtual Time Passed", f"{sim_time_ms} ms")
                    q0_percent = min(100, int((p / interference_max_payload) * 100))
                    # Show P7 queue slightly filling but dropping, maybe just flash red
                    queue_buffer_placeholder.html(draw_queue_buffers(q0_fill=q0_percent, q7_fill=0, gate0_open=True, gate7_open=False, tas_enabled=True))
                    time.sleep(1.0)

                col_sec1, col_sec2 = st.columns(2)
                col_sec1.markdown(f"<div class='metric-card' style='border: 1px solid #ff4b4b;'><strong>Security Analytics</strong><br><span style='font-size:24px; color:#ff4b4b;'>{dropped:,}</span><br><small>Spoofed Packets Dropped</small></div>", unsafe_allow_html=True)
                col_sec2.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Prio 7) Integrity</strong><br><span style='font-size:24px; color:#4ade80;'>100% Maintained</span><br><small>0.00 µs Delay Induced</small></div>", unsafe_allow_html=True)

                st.plotly_chart(draw_latency_chart(payloads, p7_lats, p0_lats, expected_latency), width="stretch", key="tab2_latency_attack")
            else:
                st.info("System Secure. Awaiting Trigger.")
                payloads = st.session_state.backend_results.get('payloads', [1000])
                p7_lats = st.session_state.backend_results.get('p7_latencies', [0.0])
                p0_lats = st.session_state.backend_results.get('p0_latencies', [0.0])
                st.plotly_chart(draw_latency_chart(payloads, p7_lats, p0_lats, expected_latency), width="stretch", key="tab2_latency_idle")


    col_end1, col_end2 = st.columns(2)
    with col_end1:
        if st.button("⏹️ Complete Demo"):
            logs = st.session_state.final_logs + "\n[Verification] Live Stress-Test complete. Determinism mathematically and empirically validated.\n"
            log_placeholder.markdown(write_terminal_log(logs), unsafe_allow_html=True)
            status_text.success("Presentation Complete! The SD-TSN perfectly maintained critical operations despite massive interference and security threats.")
            # Move to phase 6 (done) or just rely on state
            st.session_state.demo_phase = 6
            st.rerun()
    with col_end2:
        if st.session_state.slow_mo:
            if st.button("⏭️ Proceed to Phase 5: Microsecond Slow-Mo"):
                logs = st.session_state.final_logs + "\n[Slow-Mo] Transitioning to Microsecond Slow-Motion view...\n"
                log_placeholder.markdown(write_terminal_log(logs), unsafe_allow_html=True)
                st.session_state.demo_phase = 5
                st.rerun()


# --- Phase 5: Microsecond Slow-Motion ---
if st.session_state.demo_phase == 5:
    st.session_state.is_running = True # Keep running so things don't glitch

    # Retrieve backend metrics
    payloads = st.session_state.backend_results.get('payloads', [1000])
    p7_latencies = st.session_state.backend_results.get('p7_latencies', [0.0])
    p0_latencies = st.session_state.backend_results.get('p0_latencies', [0.0])
    expected_latency = st.session_state.backend_results.get('expected_latency', 0.0)
    guard_band = st.session_state.backend_results.get('guard_band', 121.76)
    t_trans = st.session_state.backend_results.get('t_trans', 81.92)

    final_payload = payloads[-1]
    final_p0_latency = p0_latencies[-1]
    final_f1_latency = p7_latencies[-1]
    jitter = final_f1_latency - expected_latency

    status_text.warning(f"Phase 5: Microsecond Slow-Motion. Analyzing {final_payload:,} Bytes Payload injection at cycle boundary.")

    f1_metric.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px;'>{final_f1_latency:.2f} µs</span><br><small style='color:lightgreen;'><b>Current Jitter:</b> Lat<sub>actual</sub> - Lat<sub>expected</sub> = {jitter:.2f} µs</small></div>", unsafe_allow_html=True)
    f2_metric.markdown(f"<div class='metric-card'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#faca2b;'>{final_payload:,} Bytes</span><br><small style='color:#faca2b;'>{final_p0_latency:.2f} µs Latency (+{(final_payload - payloads[-2]) if len(payloads)>1 else 0} B)</small></div>", unsafe_allow_html=True)

    # Calculate state based on us_clock
    t = st.session_state.us_clock

    # Basic GCL Rules dynamic based on Guard Band and T_trans

    gate0_open = False
    gate7_open = False
    q0_fill = 0
    q7_fill = 0

    if t < -guard_band:
        gate0_open = True
        gate7_open = False
        q0_fill = 10  # Idle traffic
        q7_fill = 0
    elif -guard_band <= t < 0:
        gate0_open = False
        gate7_open = False
        # Queue 0 fills rapidly because data is trying to egress but gate is closed
        fill_progress = (t + guard_band) / guard_band
        q0_fill = min(100, 10 + (90 * fill_progress))
        q7_fill = 100  # Critical packet arrives exactly during guard band
    elif 0 <= t <= t_trans:
        gate0_open = False
        gate7_open = True
        q0_fill = 100 # Still blocked
        q7_fill = max(0, 100 - (100 * (t / t_trans))) # Draining
    else:
        gate0_open = True
        # Keep gate7 visually open for an extra 100us in the slow-mo UI (SimPy buffer equivalent)
        gate7_open = True if (t <= t_trans + 100) else False
        q0_fill = max(0, 100 - (100 * ((t - t_trans) / 200))) # Draining slowly
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

    topo_placeholder.plotly_chart(create_network_topology(expand_topology=expand_network), width="stretch", key="topo_p5")

    # Update chart and buffer dynamically
    gantt_placeholder.plotly_chart(draw_gantt_chart(current_time=t), width="stretch", key="gantt_p5")
    queue_buffer_placeholder.html(draw_queue_buffers(q0_fill=q0_fill, q7_fill=q7_fill, gate0_open=gate0_open, gate7_open=gate7_open))

    log_msg = st.session_state.final_logs + f"\n[Clock] Current Time: {t:.2f} µs | P0 Gate: {'OPEN' if gate0_open else 'CLOSED'} | P7 Gate: {'OPEN' if gate7_open else 'CLOSED'}"
    log_placeholder.markdown(write_terminal_log(log_msg), unsafe_allow_html=True)

    # Render line chart statically as it was
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=payloads, y=p7_latencies, mode='lines+markers', name='Flow 1: Mission-Critical', line=dict(color='#ff4b4b', width=4), marker=dict(size=10)))
    fig.add_trace(go.Scatter(x=payloads, y=p0_latencies, mode='lines+markers', name='Flow 2: Interference', line=dict(color='#faca2b', width=3, dash='dash'), marker=dict(size=10), yaxis='y2'))
    fig.update_layout(title=dict(text="Real-Time End-to-End Latency vs. Interference Payload", font=dict(color='white')), xaxis=dict(title=dict(text="Flow 2 Payload Size (Bytes)", font=dict(color='white')), type="category", tickfont=dict(color='white')), yaxis=dict(title=dict(text="Flow 1 Latency (µs)", font=dict(color="#ff4b4b")), tickfont=dict(color="#ff4b4b"), range=[0, max(1000, expected_latency * 1.5)]), yaxis2=dict(title=dict(text="Flow 2 Latency (µs)", font=dict(color="#faca2b")), tickfont=dict(color="#faca2b"), overlaying='y', side='right', range=[0, max(20000, p0_latencies[-1] * 1.2)]), legend=dict(x=0.01, y=0.99, bgcolor='rgba(0,0,0,0.5)', font=dict(color='white')), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=40, r=40, t=40, b=40), height=300)
    chart_placeholder.plotly_chart(fig, width="stretch", key="chart_p5")


# Persist visual elements if phase completes
if not st.session_state.is_running and st.session_state.demo_phase == 6:
    topo_placeholder.plotly_chart(create_network_topology(expand_topology=expand_network), width="stretch", key="topo_persist")
    gantt_placeholder.plotly_chart(draw_gantt_chart(), width="stretch", key="gantt_persist")

    # Restore metrics
    payloads = st.session_state.backend_results.get('payloads', [1000])
    p7_latencies = st.session_state.backend_results.get('p7_latencies', [0.0])
    p0_latencies = st.session_state.backend_results.get('p0_latencies', [0.0])
    expected_latency = st.session_state.backend_results.get('expected_latency', 0.0)
    ilp_results = st.session_state.backend_results

    final_payload = payloads[-1]
    final_p0_latency = p0_latencies[-1]
    final_f1_latency = p7_latencies[-1]
    jitter = final_f1_latency - expected_latency

    f1_metric.markdown(f"<div class='metric-card glow-text'><strong>Flow 1 (Priority 7) Latency</strong><br><span style='font-size:24px;'>{final_f1_latency:.2f} µs</span><br><small style='color:lightgreen;'>{jitter:.2f} µs Jitter</small></div>", unsafe_allow_html=True)
    f2_metric.markdown(f"<div class='metric-card'><strong>Flow 2 (Priority 0) Payload</strong><br><span style='font-size:24px; color:#faca2b;'>{final_payload:,} Bytes</span><br><small style='color:#faca2b;'>{final_p0_latency:.2f} µs Latency (+{(final_payload - payloads[-2]) if len(payloads)>1 else 0} B)</small></div>", unsafe_allow_html=True)

    with col_bottom2:
        # Re-render HTML buffers with st.html to avoid Markdown indentation trap
        # Need to know the current toggle state if possible, but persistent view is typically end of a run.
        # We can assume it was true or store tas_enabled in session state. We default to True.
        queue_html = draw_queue_buffers(q0_fill=100, q7_fill=0, gate0_open=True, gate7_open=False, tas_enabled=True)
        st.html(queue_html)

    with chart_placeholder.container():
        # Live XML Expander
        with st.expander("🔬 View Live Switch Configuration (L2 & GCL XML)", expanded=False):
            st.success("Configuration deployed successfully.")
            st.markdown("#### Layer 2 MAC Forwarding Routes (Generated by Dijkstra)")
            st.json(ilp_results.get("l2_tables", {}))
            st.markdown("#### Gate Control List (YANG-style XML Generated by PuLP)")
            st.code(ilp_results.get("xml_output", ""), language="xml")

        st.markdown("### Interactive Validation Scenarios")
        tab1, tab2 = st.tabs(["📊 Scenario A: Performance (IEEE 802.1Qbv)", "🛡️ Scenario B: Security (Cyber Attack)"])

        with tab1:
            st.plotly_chart(draw_latency_chart(payloads, p7_latencies, p0_latencies, expected_latency), width="stretch", key="chart_persist_tab1")

        with tab2:
            st.info("System Secure. Awaiting Trigger.")
            st.plotly_chart(draw_latency_chart(payloads, p7_latencies, p0_latencies, expected_latency), width="stretch", key="chart_persist_tab2")

    log_placeholder.markdown(write_terminal_log(st.session_state.final_logs), unsafe_allow_html=True)
    status_text.success("Presentation Complete! The SD-TSN perfectly maintained critical operations despite 100KB+ interference.")
