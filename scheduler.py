"""
Integer Linear Programming (ILP) Scheduler for Time-Aware Shapers (TAS)

This module is the mathematical core of the SD-TSN controller. It uses the `PuLP` library
to calculate the exact microsecond (µs) transmission offsets for critical network flows.
It strictly enforces latency boundaries and calculates the critical "Guard Band" required
to protect high-priority traffic from massive background interference.
"""

import pulp
import math
from typing import List, Dict, Tuple
from models import Flow, Topology

class ILPScheduler:
    """
    Formulates and solves the scheduling constraints for IEEE 802.1Qbv switches.
    """
    def __init__(self, topology: Topology, routing: Dict[str, List[str]], link_speed_mbps: int = 100):
        self.topology = topology
        self.routing = routing

        # Physical Link Constants
        # `link_speed_mbps`: How fast data moves across the copper wire (e.g., 100 Mbps).
        self.link_speed_mbps = link_speed_mbps
        # `d_proc`: Store-and-forward processing delay inside the hardware switch chip (2.0 µs).
        self.d_proc = 2.0
        # `compensation`: A small buffer (1.0 µs) added to the start/end of a scheduled window to handle physical jitter.
        self.compensation = 1.0
        # `MTU` (Maximum Transmission Unit): The largest possible standard Ethernet frame (1500 bytes payload + 22 bytes overhead).
        self.MTU = 1522

        # The SD-TSN Guard Band Formula:
        # A low-priority (Best-Effort) frame cannot be preempted once it starts transmitting on the wire.
        # If a massive 1522-byte delivery truck (Priority 0) blocks the road right as our ambulance (Priority 7) arrives,
        # the ambulance is delayed. To prevent this, we mathematically calculate exactly how long it takes a 1522-byte
        # truck to clear the road at our current link speed, and we close the Priority 0 gate exactly that long before
        # the Priority 7 window opens.
        # Formula: Time (us) = (Bits) / (Speed Mbps) -> (1522 * 8) / 100 = 121.76 µs
        raw_guard_band_us = (self.MTU * 8) / self.link_speed_mbps
        self.guard_band = math.ceil(raw_guard_band_us) + 2.0

    def transmission_duration(self, payload_bytes: int) -> float:
        """Calculate transmission duration in microseconds for a given payload + framing."""
        # Ethernet overhead is 18 bytes (14 header + 4 FCS) + 20 bytes (Preamble + IPG) = 38 bytes
        # Let's assume payload_size includes all L2 overhead for simplicity or add standard overhead.
        # Flow 1 is 1024 Bytes payload. The problem states Flow 1 has 1024 Bytes payload.
        # Total bits = (payload_bytes + 38) * 8
        total_bits = (payload_bytes + 38) * 8
        speed_bps = self.link_speed_mbps * 1_000_000
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

        # Mathematical Constraints enforcing SD-TSN Determinism:

        # 1. End-to-End Latency Constraint
        # The packet must depart the source and arrive at the final destination
        # completely before its strict `max_latency` deadline expires.
        prob += t_offset[edges[-1]] + t_trans - t_offset[edges[0]] <= flow.max_latency, "Max_Latency_Constraint"

        # 2. Causality and Switch Processing Delay Constraint
        # A switch cannot forward a packet before it has fully received it AND
        # finished processing it (d_proc, e.g., 2.0 µs store-and-forward delay).
        for i in range(len(edges) - 1):
            e_prev = edges[i]
            e_next = edges[i+1]
            prob += t_offset[e_next] >= t_offset[e_prev] + t_trans + self.d_proc, f"Causality_{e_prev}_{e_next}"

        # 3. Transmission Window Constraint (with Jitter Compensation)
        # The transmission must occur entirely within the flow's period.
        # We also add a small `compensation` value (1.0 µs) to both the start and
        # end of the calculated window to mathematically mitigate any real-world jitter.
        for e in edges:
            prob += t_offset[e] - self.compensation >= 0, f"Compensation_Start_{e}"
            prob += t_offset[e] + t_trans + self.compensation <= flow.period, f"Period_End_{e}"

        # 4. Guard Band (GB) & Flow Isolation logic
        # Flow 2 is background traffic (Priority 0). To prevent a massive MTU-sized Prio 0 frame
        # from blocking the link right as Flow 1 needs to transmit, the system uses a Guard Band (121.76 µs).
        # This isn't an ILP constraint for Prio 7, but rather dictates how the Prio 0 Gate Control List is generated later.

        # Solve the ILP Model using CBC Solver
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
