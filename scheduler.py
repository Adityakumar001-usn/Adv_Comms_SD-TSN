import pulp
from typing import List, Dict, Tuple
from models import Flow, Topology

class ILPScheduler:
    def __init__(self, topology: Topology, routing: Dict[str, List[str]]):
        self.topology = topology
        self.routing = routing

        # Constants
        self.LINK_SPEED_MBPS = 100
        self.d_proc = 2.0  # microseconds
        self.guard_band = 121.76  # microseconds
        self.compensation = 1.0  # microseconds
        self.MTU = 1522  # Bytes

    def transmission_duration(self, payload_bytes: int) -> float:
        """Calculate transmission duration in microseconds for a given payload + framing."""
        # Ethernet overhead is 18 bytes (14 header + 4 FCS) + 20 bytes (Preamble + IPG) = 38 bytes
        # Let's assume payload_size includes all L2 overhead for simplicity or add standard overhead.
        # Flow 1 is 1024 Bytes payload. The problem states Flow 1 has 1024 Bytes payload.
        # Total bits = (payload_bytes + 38) * 8
        total_bits = (payload_bytes + 38) * 8
        speed_bps = self.LINK_SPEED_MBPS * 1_000_000
        # Time in seconds = total_bits / speed_bps
        # Time in microseconds = (total_bits / speed_bps) * 1_000_000
        duration_us = (total_bits / speed_bps) * 1_000_000
        return duration_us

    def schedule_flow(self, flow: Flow) -> Dict[Tuple[str, str], float]:
        """
        Schedules a single time-sensitive flow (Flow 1) across its path using ILP.
        Returns a dictionary mapping each edge (src, dst) to its transmission offset in microseconds.
        """
        path = self.routing.get(flow.flow_id)
        if not path:
            raise ValueError(f"No routing path found for flow {flow.flow_id}")

        # The path edges
        edges = [(path[i], path[i+1]) for i in range(len(path) - 1)]

        # Calculate L2 transmission duration
        t_trans = self.transmission_duration(flow.payload_size)

        # Define the problem: Minimize end-to-end latency
        prob = pulp.LpProblem(f"Schedule_{flow.flow_id}", pulp.LpMinimize)

        # Decision variables: t_offset[e] for each edge e in path.
        # The transmission offset must be >= 0 and < flow.period.
        t_offset = pulp.LpVariable.dicts("offset", edges, lowBound=0, upBound=flow.period, cat=pulp.LpContinuous)

        # Objective function: Minimize the arrival time at the destination
        # The arrival time at the destination is the offset on the last edge + transmission duration
        prob += t_offset[edges[-1]] + t_trans, "Minimize_End_to_End_Latency"

        # Constraints
        # 1. End-to-End Latency Constraint: total latency <= max_latency
        prob += t_offset[edges[-1]] + t_trans - t_offset[edges[0]] <= flow.max_latency, "Max_Latency_Constraint"

        # 2. Causality and Processing Delay: offset on next edge >= offset on prev edge + transmission + processing
        for i in range(len(edges) - 1):
            e_prev = edges[i]
            e_next = edges[i+1]
            prob += t_offset[e_next] >= t_offset[e_prev] + t_trans + self.d_proc, f"Causality_{e_prev}_{e_next}"

        # 3. Transmission Start Constraint (offset + transmission time <= period)
        # We also need to add the compensation value C to ends according to the paper?
        # The paper says: "Compensation C: This value is added to both ends of the required transmission slot to mitigate real-world jitter."
        # This means the reserved window is [offset - C, offset + t_trans + C].
        # So offset - C >= 0, and offset + t_trans + C <= period.
        for e in edges:
            prob += t_offset[e] - self.compensation >= 0, f"Compensation_Start_{e}"
            prob += t_offset[e] + t_trans + self.compensation <= flow.period, f"Period_End_{e}"

        # 4. We only have one time-sensitive flow in this scenario to explicitly schedule!
        # Thus, Flow Isolation constraints (between multiple TS flows) are trivially satisfied.
        # Flow 2 is background traffic (Priority 0) and simply transmits outside of Flow 1's window + Guard Band.

        # Solve the problem
        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        if pulp.LpStatus[prob.status] != "Optimal":
            raise ValueError(f"Could not find an optimal schedule for flow {flow.flow_id}. Status: {pulp.LpStatus[prob.status]}")

        schedule = {e: pulp.value(t_offset[e]) for e in edges}
        return schedule

if __name__ == "__main__":
    from models import Topology
    from cuc import MockCUC
    from routing import CNCRouting
    import json

    topo = Topology()
    cuc = MockCUC()
    flows = cuc.generate_test_flows()
    routing = CNCRouting(topo)
    routes = routing.compute_routes(flows)

    scheduler = ILPScheduler(topo, routes)

    # Schedule Flow 1
    flow1 = next(f for f in flows if f.flow_id == "Flow1")
    try:
        schedule = scheduler.schedule_flow(flow1)
        print("Flow 1 Schedule (Edge -> Offset in us):")
        for edge, offset in schedule.items():
            print(f"  {edge[0]} -> {edge[1]}: {offset:.2f} us")

        print(f"\nTransmission duration for Flow 1 (1024B): {scheduler.transmission_duration(1024):.2f} us")

        end_to_end_latency = schedule[('SW4', 'E3')] + scheduler.transmission_duration(1024) - schedule[('E1', 'SW1')]
        print(f"Calculated End-to-End Latency: {end_to_end_latency:.2f} us (Max: {flow1.max_latency} us)")

    except ValueError as e:
        print(f"Scheduling failed: {e}")
