# SD-TSN In-Vehicle Network Simulation

This project builds a real-time software simulation of a Software-Defined Time-Sensitive Network (SD-TSN) for in-vehicle networks. It implements a Centralized Network Configuration (CNC) controller that calculates routing and Time-Aware Shaper (TAS) schedules based on IEEE 802.1Qbv, and validates the deterministic transmission of mission-critical automotive traffic via a discrete-event simulation.

## Project Context
Modern automotive architectures require strict, deterministic latency for time-sensitive application data (e.g., braking, steering) while accommodating best-effort background traffic (e.g., infotainment). This simulation models a central gateway and a ring of zonal switches. By computing an Integer Linear Programming (ILP) schedule and deploying strict Gate Control Lists (GCL), the network ensures that critical traffic (Priority 7) completely bypasses the interference of large background flows (Priority 0).

## Tech Stack
*   **Language:** Python 3.10+
*   **Network Topology & Routing:** `networkx`
*   **ILP Solver:** `PuLP` (Used to enforce strict transmission offsets and guard bands)
*   **Data Plane Simulation:** `SimPy` (Discrete-event simulation)

## Getting Started

### Prerequisites
Install the required Python packages:
```bash
python3 -m pip install networkx pulp simpy
```

### Running the Simulation
To execute the end-to-end simulation test across varying payload sizes:
```bash
python3 run_simulation.py
```
This script will:
1. Build the topology and L2 routing tables.
2. Calculate the optimal ILP schedule for the time-sensitive flow.
3. Generate the XML GCL configurations mimicking a YANG schema.
4. Run 5,000ms simulations (simulating 100 consecutive transmissions of the critical flow) under varying background interference loads (3,200 up to 102,400 Bytes).
5. Output the results to the console and save a detailed JSON report to `simulation_report.json`.

---

## Architectural Details & Modules

### 1. Topology & Data Models (`models.py` & `cuc.py`)
The physical network topology is modeled as a directed graph featuring bidirectional 100 Mbps links.
*   **Endpoints:** E1, E2, E3
*   **Switches:** SW1, SW2, SW3, SW4 (Forming a ring around the Gateway)
*   **Gateway:** GW
*   **Control Plane:** PC (Used for configuration deployment, not involved in data flows).

A **Mock Centralized User Configuration (CUC)** generates two specific test flows:
*   **Flow 1 (Time-Sensitive):** Originates at E1, destined for E3. Priority 7. Period: 50ms ($50,000 \mu s$). Payload: 1024 Bytes. Max Latency: $500 \mu s$.
*   **Flow 2 (Interference):** Originates at E2, destined for E3. Priority 0 (Best-Effort). Period: 10ms ($10,000 \mu s$). Payload varies from 3,200 Bytes up to massive 102,400 Bytes.

### 2. CNC Routing & L2 Tables (`routing.py`)
The Centralized Network Configuration (CNC) controller calculates the shortest L2 paths across the directed graph.
It auto-generates sequential dummy MAC addresses (e.g., `00:00:00:00:00:03` for E3) and integer port mappings. Finally, it constructs Layer 2 Lookup Tables for every switch mapping destination MACs and VLAN IDs (representing priority) to specific egress ports.

### 3. CNC ILP Scheduler (`scheduler.py`)
To ensure deterministic latency for Flow 1, the `PuLP` library defines a rigorous mathematical Integer Linear Programming (ILP) model.
*   **Objective:** Minimize end-to-end latency.
*   **Constraints:**
    *   Strict causality tracking processing delays ($d_{proc} = 2 \mu s$).
    *   Link transmission times based on 100 Mbps Ethernet speeds.
    *   Pre-allocation of compensation values ($C = 1 \mu s$) to mitigate real-world jitter.
    *   Strict overall maximum latency of $\le 500 \mu s$.
*   **Result:** The solver calculates a precise transmission offset for every hop. The anticipated end-to-end latency is explicitly solved at **$345.84 \mu s$**.

### 4. Gate Control List (GCL) Generation (`gcl.py`)
Based on the ILP offsets, this module translates the mathematical schedules into actionable Gate Control Lists (IEEE 802.1Qbv).
*   Calculates the network hyper-period ($50,000 \mu s$).
*   Calculates microsecond-accurate gate triggers for Priority 7 and Priority 0.
*   **Guard Band:** Injects a critical $121.76 \mu s$ Guard Band immediately prior to the Priority 7 transmission window. During this Guard Band, Priority 0 gates are explicitly closed to prevent interference from in-flight best-effort frames.
*   Outputs the full schedule into an **XML file (`network_config.xml`)** structurally mimicking the YANG standard.

### 5. SimPy Discrete-Event Simulation (`simulator.py`)
To validate the ILP schedule, a highly granular discrete-event simulator is built using `SimPy`.
*   **Strict GCL Enforcement:** Switches implement egress ports with dedicated priority queues (`simpy.Store`) and a prioritized physical transmitter (`simpy.PriorityResource`).
*   **Preemption & Fragmentation:** To handle massive Flow 2 interference payloads (up to 102,400 Bytes) without violating IEEE 802.1Qbv, the simulator performs realistic MTU fragmentation (1,500 Bytes). Priority 0 frames only transmit if they fit within the remaining open gate window. Otherwise, they release the link, allowing the Priority 7 traffic to preempt the massive background streams perfectly on time.

### Conclusion & Success Criteria
Executing `run_simulation.py` demonstrates that regardless of whether the background interference payload is 3,200 Bytes or 102,400 Bytes, the Time-Sensitive Flow 1 packets bypass the queues perfectly according to the GCL schedule.
The logged end-to-end latency remains locked at exactly **$345.84 \mu s$**, successfully meeting the strict $\le 500 \mu s$ mission-critical constraint and proving the determinism of the SD-TSN architecture.
