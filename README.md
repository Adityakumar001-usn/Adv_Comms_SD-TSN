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

## Core Simulation Architecture

The backend engine validates the determinism of the network using four key components, all of which are thoroughly commented in the source code to explain the underlying math and simulation logic:

### 1. Data Models & Topology (`models.py`, `cuc.py`)
*   **Topology:** A directional NetworkX graph representing a zonal automotive architecture featuring Endpoints (E1, E2, E3), Switches (SW1, SW2, SW3, SW4), and a Gateway (GW). All physical links operate at 100 Mbps.
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
*   Generates exact open/close timings for Priority 7 and Priority 0 queues across all switches to physically enforce the ILP constraints.
*   Outputs the finalized switch schedules to a structured XML (`network_config.xml`) mimicking a YANG model. During the Streamlit Live Demo Phase 3, this file is explicitly overwritten to allow real-time inspection of the hardware rules.

### 4. SimPy Discrete-Event Simulation (`simulator.py`, `run_simulation.py`)
*   A custom SimPy "Physics Engine" modeling the physical 100 Mbps links, switch forwarding delays, and strict Priority queuing (enforcing the calculated GCL timings).
*   Runs automated test suites featuring consecutive transmissions of Flow 1 against escalating Flow 2 payloads.
*   **Validation:** The simulation proves the architecture's determinism. Flow 1 maintains a strict, unwavering latency (0.00 µs jitter) regardless of whether Flow 2 transmits 3.2KB or 102.4KB of interference. Outputs results to `simulation_report.json`.

---

## Output Artifacts

Running the core simulation generates two primary artifacts automatically saved to the repository root:

*   **`network_config.xml`**: A fully structured XML file mimicking a YANG data model. It contains the exact Layer 2 routing lookup tables and the Time-Aware Shaper (TAS) Gate Control List (GCL) transmission schedules for every egress port on every switch and gateway in the network.
*   **`simulation_report.json`**: A detailed data dump validating the determinism of the network. It records the payload sizes, the number of delivered packets, and the precise minimum, maximum, and average latencies for both Priority 7 and Priority 0 flows across the test suite.

---

## Interactive Digital Twin Dashboard (`app.py`)

A professional, interactive dashboard built with Streamlit serves as the primary presentation layer. It transforms the raw backend data into a highly visual, phase-based engineering "Digital Twin" presentation, fully driven by live backend computations.

### Dashboard Features

*   **Sequential Live Demo Logic:** A "▶️ Start Live Demo" button triggers a fully animated state machine that guides the audience through the critical engineering phases:
    1.  **🟢 Digital Twin Construction (Layer 1 & 2):** Dynamically animates the topology instantiation, physical link connections, and hop-by-hop L2 routing paths.
    2.  **🟡 Optimization (Layer 3 ILP):** Mathematically solves the Time-Aware Shaper (TAS) scheduling constraints. Features a dynamic **"X-Ray" Transparency Checklist** that proves Flow Isolation, Guard Band, and Boundary constraints as they are solved by PuLP.
    3.  **🟠 Configuration & SimPy Init:** Compiles the YANG-style XML, deploys the Gate Control Lists to the switches, and initializes the discrete-event clock.
    4.  **🔴 Interactive Validation Scenarios:** Provides tabbed views for advanced testing:
        *   **Scenario A (A/B Testing):** Compare strict priority (TAS disabled) against shaped traffic (TAS enabled) and watch the dynamic queue progress bars fill as the SimPy clock ticks.
        *   **Scenario B (Security Attack):** Simulate a rogue node injecting spoofed Priority 7 packets, demonstrating the CNC's ability to isolate unauthorized ingress and drop packets.
    5.  **🟣 Microsecond Slow-Motion:** A deep-dive interactive mode allowing users to step forward (+10 µs increments) through a single network cycle. Watch physical MTU fragmentation cause Priority 0 queues to back up against the Guard Band, while the Priority 7 payload sails through.

### Dynamic Backend Integration & Controls

The dashboard is completely interactive and no longer hardcoded. All visuals, mathematical models, and network metrics are dynamically rebuilt from scratch by the `scheduler.py` and `simulator.py` engines whenever you change a setting.

Using the **Simulation Settings Sidebar**, users can adjust:
*   **Expand Network (Add SW5 & E4):** Watch the zonal architecture dynamically extend. `NetworkX` instantly draws the new topology, and Dijkstra's algorithm immediately recalculates the Layer 2 forwarding routes to accommodate the new endpoints.
*   **Physical Link Speed:** Toggle between Legacy Fast Ethernet (`100 Mbps`) and Gigabit Ethernet (`1000 Mbps`). This upgrades every single edge in the NetworkX graph (Endpoints, Switches, Gateways). Watch the math solver instantly shrink the required Guard Band from `121.76 µs` down to `12.17 µs` because Gigabit hardware clears the 1500-Byte MTU interference ten times faster!
*   **Critical Payload Size (Bytes):** Slide from `128B` up to `1500B` to see the ILP dynamically stretch the required Priority 7 transmission window (`t_trans`).
*   **Interference Payload Max (Bytes):** Slide from `1,000B` up to `150,000B` to define the severity of the background traffic stress test in Phase 4.
*   **Simulation Window (ms):** Increase the total runtime of the Scenario B Cyber Attack up to `1,000 ms`. The longer the simulation runs, the more spoofed Priority 7 packets the CNC controller will identify and drop live on screen!

When "Start Live Demo" is clicked, `app.py` recalculates the precise Guard Band requirements using PuLP, regenerates the GCL, and executes the physical layer SimPy validation in real-time based strictly on these selected parameters.

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
