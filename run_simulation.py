from models import Topology, Flow
from cuc import MockCUC
from routing import CNCRouting
from scheduler import ILPScheduler
from gcl import GCLGenerator
from simulator import TSNSimulator
import json

def run_simulation_tests():
    payload_sizes = [3200, 6400, 12800, 25600, 51200, 102400]
    simulation_duration = 5000000  # 5000 ms = 5,000,000 us

    # Initialize Base Models
    topo = Topology()
    cuc = MockCUC()
    base_flows = cuc.generate_test_flows()
    routing = CNCRouting(topo)
    routes = routing.compute_routes(base_flows)

    # Calculate Schedule and GCL based on Flow 1 (constant)
    scheduler = ILPScheduler(topo, routes)
    flow1 = next(f for f in base_flows if f.flow_id == "Flow1")

    schedule = scheduler.schedule_flow(flow1)
    t_trans = scheduler.transmission_duration(flow1.payload_size)

    gcl_gen = GCLGenerator(topo, routing.port_map)
    hyper_period = gcl_gen.calculate_hyper_period(base_flows)
    gcl_config = gcl_gen.generate_gcl(schedule, t_trans, hyper_period, flow1.period)

    # Export GCL configuration to XML for documentation/YANG representation
    l2_tables = routing.generate_l2_lookup_tables(base_flows)
    xml_output = gcl_gen.generate_xml_configuration(l2_tables, gcl_config, hyper_period)
    with open("network_config.xml", "w") as f:
        f.write(xml_output)

    print("="*60)
    print("SD-TSN In-Vehicle Network Simulation Report")
    print("="*60)
    print(f"Flow 1 (Time-Sensitive): Payload {flow1.payload_size} Bytes, Max Latency {flow1.max_latency} us")
    print(f"Expected ILP Calculated Latency for Flow 1: 345.84 us")
    print("-" * 60)

    report_data = []

    for payload in payload_sizes:
        print(f"\nRunning simulation with Flow 2 Payload Size: {payload} Bytes...")

        # Update Flow 2 payload
        flows = []
        for f in base_flows:
            if f.flow_id == "Flow2":
                flows.append(Flow(
                    flow_id="Flow2",
                    source="E2",
                    destination="E3",
                    period=10000,
                    priority=0,
                    payload_size=payload,
                    max_latency=0
                ))
            else:
                flows.append(f)

        # Initialize Simulator
        sim = TSNSimulator(topo, routing, gcl_config, hyper_period)
        for flow in flows:
            sim.start_flow(flow)

        # Run Simulation
        sim.run(simulation_duration)

        # Analyze Results
        f1_latencies = sim.latencies.get("Flow1", [])
        f2_latencies = sim.latencies.get("Flow2", [])

        if not f1_latencies:
            print("Error: Flow 1 did not deliver any packets!")
            continue

        f1_avg = sum(f1_latencies) / len(f1_latencies)
        f1_max = max(f1_latencies)
        f1_min = min(f1_latencies)

        f2_avg = sum(f2_latencies) / len(f2_latencies) if f2_latencies else 0
        f2_max = max(f2_latencies) if f2_latencies else 0

        success = f1_max <= flow1.max_latency

        report_data.append({
            "flow2_payload_bytes": payload,
            "flow1_delivered": len(f1_latencies),
            "flow1_avg_latency_us": f1_avg,
            "flow1_max_latency_us": f1_max,
            "flow1_min_latency_us": f1_min,
            "flow2_delivered": len(f2_latencies),
            "flow2_avg_latency_us": f2_avg,
            "flow2_max_latency_us": f2_max,
            "success": success
        })

        print(f"  Flow 1 Delivered: {len(f1_latencies)} (Expected ~100)")
        print(f"  Flow 1 Latency -> Min: {f1_min:.2f} us, Avg: {f1_avg:.2f} us, Max: {f1_max:.2f} us")
        print(f"  Flow 2 Delivered: {len(f2_latencies)}, Max Latency: {f2_max:.2f} us")
        print(f"  Strict Determinism Maintained: {'YES' if success else 'NO'}")

    print("\n" + "="*60)
    print("Conclusion: ")
    all_success = all(data['success'] for data in report_data)
    if all_success:
        print("Simulation SUCCESSFUL. Flow 1 strictly maintained <= 500us latency across all background traffic loads.")
    else:
        print("Simulation FAILED. Flow 1 experienced latency violations due to background traffic interference.")

    with open("simulation_report.json", "w") as f:
        json.dump(report_data, f, indent=4)
    print("Report details saved to simulation_report.json")

if __name__ == "__main__":
    run_simulation_tests()
