# SD-TSN In-Vehicle Network Simulation

This project builds a real-time software simulation of a **Software-Defined Time-Sensitive Network (SD-TSN)** designed for modern, mission-critical in-vehicle zonal architectures.

It implements a Centralized Network Configuration (CNC) controller that calculates routing and Time-Aware Shaper (TAS) schedules (IEEE 802.1Qbv), and uses a discrete-event simulation to validate the strictly deterministic transmission of automotive traffic.

---

## Project Context and Goal

Modern automotive architectures require a mix of best-effort background traffic (e.g., infotainment, diagnostics) and hard-real-time mission-critical data (e.g., LiDAR, steering control). This project simulates an SD-TSN environment where a mission-critical flow maintains a strict **<= 500µs** end-to-end latency boundary, completely unaffected by massive bursts of lower-priority background interference.

### Tech Stack & Environment

*   **Language:** Python 3.10+
*   **Network Topology:** `networkx`
*   **ILP Solver:** `PuLP` (Provides seamless automated TAS schedule execution)
*   **Data Plane Simulation:** `SimPy` (Discrete-event network simulation)
*   **Interactive Dashboard:** `Streamlit`, `Plotly`, `pandas`

---

## Core Simulation Architecture (Phase 1)

The backend engine validates the determinism of the network using four key components:

### 1. Data Models & Topology (`models.py`, `cuc.py`)
*   **Topology:** A directional graph representing a zonal automotive architecture featuring Endpoints (E1, E2, E3), Switches (SW1, SW2, SW3, SW4), and a Gateway (GW). All physical links operate at 100 Mbps.
*   **Flow Configuration (CUC):** A mock Centralized User Configuration module generates two core test flows:
    *   **Flow 1 (Time-Sensitive):** E1 -> SW1 -> SW3 -> GW -> E3. Priority 7, 50ms period, 1024 Byte payload, strict 500µs max latency constraint.
    *   **Flow 2 (Interference):** E2 -> SW2 -> SW4 -> GW -> E3. Priority 0, 10ms period, variable payload (3,200 Bytes up to 102,400 Bytes).

### 2. CNC Routing & ILP Scheduler (`routing.py`, `scheduler.py`)
*   **Routing:** Automatically calculates the shortest-path critical path for all generated flows.
*   **TAS Scheduling (PuLP):** An Integer Linear Programming (ILP) model calculates precision transmission offsets for every switch egress port. The solver strictly enforces:
    *   **Transmission Start Constraints:** Flows must transmit within their required periods.
    *   **Flow Isolation Constraints:** Prevents simultaneous egress port buffer occupation.
    *   **Link Resource Constraints:** Ensures no time slots on shared links overlap. To protect Flow 1 from MTU-sized (1500B) fragments of Flow 2, the scheduler dynamically calculates a **121.76 µs Guard Band**.
    *   **Latency Constraints:** Hard limits ensuring Flow 1 never exceeds 500µs.

### 3. Gate Control List (GCL) Generation (`gcl.py`)
*   Calculates the network-wide hyper-period (50,000 µs based on the LCM of the flows).
*   Generates exact open/close timings for Priority 7 and Priority 0 queues across all switches.
*   Outputs the finalized switch schedules to a structured XML (`network_config.xml`) mimicking a YANG model.

### 4. SimPy Discrete-Event Simulation (`simulator.py`, `run_simulation.py`)
*   A custom SimPy simulation modeling the physical 100 Mbps links, switch forwarding delays, and strict Priority queuing (enforcing the calculated GCL timings).
*   Runs automated test suites featuring 100 consecutive transmissions of Flow 1 against escalating Flow 2 payloads.
*   **Validation:** The simulation proves the architecture's determinism. Flow 1 maintains a strict, unwavering latency of **exactly 345.84 µs** (0.00 µs jitter) regardless of whether Flow 2 transmits 3.2KB or 102.4KB of interference. Outputs results to `simulation_report.json`.

---

## Interactive Presentation Dashboard (Phase 2)

An interactive, web-based dashboard built with Streamlit (`app.py`) serves as the primary presentation layer for the simulation results. It dynamically visualizes the determinism of the network.

### Dashboard Features (`app.py`)

*   **Interactive Topology:** A custom NetworkX/Plotly graph displaying the zonal architecture, highlighting the critical path (Red) and interference path (Amber).
*   **Live Simulation Execution:** A "▶️ Run Live Simulation" button simulates the background interference scaling (3.2KB to 102.4KB), triggering real-time UI updates via `time.sleep()`.
*   **Dynamic Metrics:** `st.metric` cards cleanly display the unwavering 345.84 µs / 0.00 µs jitter latency for Flow 1 alongside the escalating latency estimation for Flow 2.
*   **Animated Results Chart:** A dual-axis Plotly line graph animates step-by-step as the simulation progresses.
*   **GCL Schedule Gantt Chart:** A pre-computed static Plotly Gantt chart visualizing the switch egress schedule, including explicit hover text annotations for the 121.76 µs Guard Band protecting the Priority 7 queue.
*   **Simulated Terminal Logs:** A code-formatted text block streams simulated backend initialization and execution logs (e.g., "[PuLP] Validating...", "[SimPy] Simulating interference iteration 1/5...") during the execution loop.

---

## Installation & Usage

### 1. Prerequisites

Ensure you have Python 3.10+ installed. Install the required dependencies:

```bash
pip install networkx pulp simpy streamlit plotly pandas matplotlib
```

### 2. Run the Backend Simulation

To run the discrete-event network simulation and generate the `network_config.xml` and `simulation_report.json` files:

```bash
python3 run_simulation.py
```

### 3. Launch the Interactive Dashboard

To launch the real-time presentation dashboard in your browser:

```bash
streamlit run app.py
```
