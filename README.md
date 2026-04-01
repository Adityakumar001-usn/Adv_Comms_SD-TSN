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

## Output Artifacts

Running the core simulation generates two primary artifacts automatically saved to the repository root:

*   **`network_config.xml`**: A fully structured XML file mimicking a YANG data model. It contains the exact Layer 2 routing lookup tables and the Time-Aware Shaper (TAS) Gate Control List (GCL) transmission schedules for every egress port on every switch and gateway in the network.
*   **`simulation_report.json`**: A detailed data dump validating the determinism of the network. It records the payload sizes, the number of delivered packets, and the precise minimum, maximum, and average latencies for both Priority 7 and Priority 0 flows across the test suite.

---

## Interactive Guided Presentation Dashboard (Phase 2)

A professional, interactive dashboard built with Streamlit (`app.py`) serves as the primary presentation layer for audiences. It transforms the raw backend data into a highly visual, phase-based engineering presentation.

### Dashboard Features (`app.py`)

*   **Sequential Live Demo Logic:** A "▶️ Start Live Demo" button triggers a fully animated state machine that guides the audience through the four critical engineering phases:
    1.  **🟢 Discovery:** Dynamically mapping the topology and flows.
    2.  **🟡 Optimization (ILP):** Mathematically solving the Time-Aware Shaper (TAS) scheduling constraints.
    3.  **🟠 Configuration:** Compiling the YANG-style XML and deploying the Gate Control Lists to the switches.
    4.  **🔴 Live Stress-Test:** Running a live background interference loop (3.2KB to 102.4KB payloads).
*   **Enhanced Topology Map:** A customized NetworkX/Plotly graph emphasizing a glowing red critical route (Flow 1) and a dashed amber background route (Flow 2).
*   **Live Metrics:** Dynamic, glowing `st.metric` cards verifying the strict 345.84 µs latency bound and 0.00 µs jitter for Flow 1 in real-time.
*   **Animated Results Chart:** A dual-axis Plotly line graph that draws the Latency vs. Payload Load stress-test results point-by-point.
*   **"Smart Gate" Gantt Chart:** A Plotly Gantt chart visualizing the switch egress schedule. It explicitly highlights the 121.76 µs Guard Band in dark red, featuring hover tooltips explaining how the safety gap prevents "delivery trucks from blocking the ambulance."
*   **Simulated Terminal Logs:** A real-time scrolling code-block that streams technical backend execution updates (e.g., "[CNC] Deploying Gate Control List...", "[SimPy] Injecting 102,400 Bytes...") synchronized perfectly with the visual phases.

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
