"""
Main Execution Runner for the SD-TSN Simulation

This script acts as the overarching orchestrator. It triggers the entire pipeline:
1. Discovery: Builds the mathematical models for the Topology and Data Flows.
2. Control Plane (CNC): Calculates the Shortest-Paths (L2 Routing).
3. Optimization: Uses PuLP to solve for deterministic transmission offsets (TAS ILP).
4. Configuration: Exports the final schedules to a YANG-style XML configuration.
5. Data Plane Validation: Uses SimPy to run a discrete-event network stress-test,
   verifying whether determinism is actually maintained.
"""

from models import Topology, Flow
from cuc import MockCUC
from routing import CNCRouting
from scheduler import ILPScheduler
from gcl import GCLGenerator
from simulator import TSNSimulator
import json
import time

def print_step(title, message, delay=1.0):
    print(f"\n[+] {title}")
    print(f"    {message}")
    time.sleep(delay)

def run_simulation_tests():
    """
    Runs the automated test suite, gradually increasing the size of
    Priority 0 (Best-Effort) interference to validate the determinism
    of Flow 1 (Priority 7).
    """
    payload_sizes = [3200, 6400, 12800, 25600, 51200, 102400]
    simulation_duration = 5000000  # 5000 ms = 5,000,000 us

    print("\n============================================================")
    print("🚗 SD-TSN In-Vehicle Network Simulation Presentation 🚗")
    print("============================================================\n")
    time.sleep(1)

    # Initialize Base Models
    print_step("Phase 1: Discovery", "Mapping Topology & Data Flows...", 1.5)
    topo = Topology()
    cuc = MockCUC()
    base_flows = cuc.generate_test_flows()
    flow1 = next(f for f in base_flows if f.flow_id == "Flow1")
    flow2 = next(f for f in base_flows if f.flow_id == "Flow2")

    print(f"    -> Flow 1 (Critical): {flow1.source} -> {flow1.destination} (Payload: {flow1.payload_size}B, Prio: {flow1.priority})")
    print(f"    -> Flow 2 (Background): {flow2.source} -> {flow2.destination} (Payload: Variable, Prio: {flow2.priority})")
    time.sleep(1)

    print_step("Phase 2: CNC Routing", "Computing optimal L2 routing paths...", 1.5)
    routing = CNCRouting(topo)
    routes = routing.compute_routes(base_flows)
    print(f"    -> Flow 1 Route: {' -> '.join(routes['Flow1'])}")
    print(f"    -> Flow 2 Route: {' -> '.join(routes['Flow2'])}")
    time.sleep(1)

    print_step("Phase 3: Mathematical Optimization (PuLP ILP)", "Calculating TAS transmission offsets & Guard Bands...", 2.0)
    scheduler = ILPScheduler(topo, routes)
    schedule = scheduler.schedule_flow(flow1)
    t_trans = scheduler.transmission_duration(flow1.payload_size)

    path = routes['Flow1']
    expected_latency = schedule[(path[-2], path[-1])] + t_trans - schedule[(path[0], path[1])]

    print(f"    -> Guard Band Calculated: {scheduler.guard_band:.2f} µs (Blocks 100Mbps MTU interference)")
    print(f"    -> Deterministic End-to-End Latency Locked at: {expected_latency:.2f} µs")
    time.sleep(1.5)

    print_step("Phase 4: Gate Control List Configuration", "Deploying YANG-style XML schedules to switches...", 1.5)
    gcl_gen = GCLGenerator(topo, routing.port_map)
    hyper_period = gcl_gen.calculate_hyper_period(base_flows)
    gcl_config = gcl_gen.generate_gcl(schedule, t_trans, hyper_period, flow1.period)

    l2_tables = routing.generate_l2_lookup_tables(base_flows)
    xml_output = gcl_gen.generate_xml_configuration(l2_tables, gcl_config, hyper_period)
    with open("network_config.xml", "w") as f:
        f.write(xml_output)
    print("    -> Wrote final hardware configuration to `network_config.xml`.")
    time.sleep(1)

    print("\n============================================================")
    print("🔬 Data Plane Verification (SimPy Discrete-Event Engine)")
    print("============================================================")
    time.sleep(1)

    report_data = []

    def execute_stress_test(name, tas_enabled=True, attack_active=False):
        print(f"\n--- {name} ---")
        time.sleep(1)

        for payload in payload_sizes:
            print(f"  > Injecting Prio 0 Interference Payload: {payload:,} Bytes...")
            time.sleep(0.5)

            # Setup network topology for attack if needed
            test_topo = Topology()
            if attack_active:
                test_topo.graph.add_node('MockAttacker', type='endpoint')
                test_topo.add_bidirectional_link('MockAttacker', 'SW1')

            test_routing = CNCRouting(test_topo)

            # Update Flow 2 payload and add rogue node if attack is active
            flows = []
            for f in base_flows:
                if f.flow_id == "Flow2":
                    flows.append(Flow("Flow2", "E2", "E3", 10000, 0, payload, 0))
                else:
                    flows.append(Flow(f.flow_id, f.source, f.destination, f.period, f.priority, f.payload_size, f.max_latency))

            if attack_active:
                flows.append(Flow("RogueFlow", "MockAttacker", "E3", 1000, 7, 1500, 0))

            # Initialize Simulator
            sim = TSNSimulator(test_topo, test_routing, gcl_config, hyper_period, tas_enabled=tas_enabled, attack_active=attack_active, link_speed_mbps=100)
            for flow in flows:
                sim.start_flow(flow)

            # Run Simulation (SimPy)
            sim.run(simulation_duration)

            # Analyze Results
            f1_latencies = sim.latencies.get("Flow1", [])
            f2_latencies = sim.latencies.get("Flow2", [])

            if not f1_latencies:
                print("    Error: Flow 1 did not deliver any packets!")
                continue

            f1_avg = sum(f1_latencies) / len(f1_latencies)
            f2_max = max(f2_latencies) if f2_latencies else 0

            jitter = f1_avg - expected_latency

            # Logging to console
            print(f"    [Prio 0] Max Latency: {f2_max:.2f} µs")

            if attack_active:
                print(f"    [Security] Spoofed Packets Dropped: {sim.dropped_spoofed_packets:,}")

            if abs(jitter) < 0.01:
                print(f"    [Prio 7] Latency: {f1_avg:.2f} µs (Jitter: 0.00 µs) -> DETERMINISTIC")
            else:
                print(f"    [Prio 7] Latency: {f1_avg:.2f} µs (Jitter: +{jitter:.2f} µs) -> LATENCY SPIKE (FAILED)")

            report_data.append({
                "scenario": name,
                "flow2_payload_bytes": payload,
                "flow1_avg_latency_us": f1_avg,
                "jitter_us": jitter,
                "dropped_packets": getattr(sim, 'dropped_spoofed_packets', 0),
                "link_speed_mbps": 100,
                "topology_expanded": False,
                "simulation_window_ms": 5000
            })
            time.sleep(0.5)

    # 1. Standard Unshaped Performance (TAS OFF)
    execute_stress_test("Scenario A1: Strict Priority Only (TAS Disabled)", tas_enabled=False)

    # 2. Shaped Performance (TAS ON)
    execute_stress_test("Scenario A2: SD-TSN Enabled (TAS Active)", tas_enabled=True)

    # 3. Security (Rogue Node)
    execute_stress_test("Scenario B: Cyber Attack (Rogue Node spoofing Prio 7)", tas_enabled=True, attack_active=True)

    print("\n============================================================")
    print("Presentation Complete.")
    print("============================================================")

    with open("simulation_report.json", "w") as f:
        json.dump(report_data, f, indent=4)
    print("Report details saved to `simulation_report.json`.")

if __name__ == "__main__":
    run_simulation_tests()
