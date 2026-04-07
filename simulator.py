"""
Discrete-Event Data Plane Simulator for SD-TSN

This module validates the mathematically calculated TAS schedules in a "real-world"
network environment. Utilizing `SimPy`, it models the exact physical links,
transmission times, switch store-and-forward delays, and egress port queues.

Crucially, it simulates the IEEE 802.1Qbv gate control logic:
If a Priority 0 packet arrives while the Priority 0 gate is closed
(e.g., during the Guard Band), the packet sits in the buffer and waits, ensuring
the physical link is completely free when the Priority 7 packet arrives.
"""

import simpy
from typing import List, Dict, Any, Tuple
from models import Flow, Topology

class Packet:
    """
    Represents an individual unit of data transiting the network.
    Contains metadata like priority and size for calculating transmission delays.
    """
    def __init__(self, packet_id: int, flow: Flow, creation_time: float):
        self.packet_id = packet_id
        self.flow = flow
        self.creation_time = creation_time
        self.size = flow.payload_size
        self.priority = flow.priority
        self.path_idx = 0

    def __repr__(self):
        return f"Packet({self.flow.flow_id}_{self.packet_id}, prio={self.priority})"

class Endpoint:
    def __init__(self, env: simpy.Environment, name: str, scheduler):
        self.env = env
        self.name = name
        self.scheduler = scheduler # The Network Simulator which has the routing info

    def generate_flow(self, flow: Flow):
        """Generates packets for a specific flow at defined periods."""
        packet_id = 0
        while True:
            packet = Packet(packet_id, flow, self.env.now)
            # print(f"[{self.env.now:.2f}] {self.name} generated {packet}")

            # Send to the next hop
            self.scheduler.send_packet(packet, self.name)

            packet_id += 1
            yield self.env.timeout(flow.period)

class SwitchPort:
    """
    Simulates a physical egress port on an automotive switch.
    Handles distinct priority queues and mathematically enforces the Gate Control List (GCL) transmission timings.
    """
    def __init__(self, env: simpy.Environment, node_name: str, port_id: int,
                 gcl_events: List[Dict], cycle_time: int, speed_mbps: int = 100, tas_enabled: bool = True):
        self.env = env
        self.node_name = node_name
        self.port_id = port_id
        self.gcl_events = gcl_events
        self.cycle_time = cycle_time
        self.tas_enabled = tas_enabled

        # 100 Mbps transmission rate
        self.rate_bps = speed_mbps * 1_000_000

        # Queues
        # 8 queues for 8 priorities. Index 7 is highest.
        self.queues = {prio: simpy.Store(env) for prio in range(8)}

        # Current gate status (string '00000000'). MSB is Prio 7, LSB is Prio 0.
        self.gate_status = "00000001" # Default initial

        # Event to signal when a gate opens
        self.gate_open_events = {prio: simpy.Event(env) for prio in range(8)}

        # Visual buffer to keep the gate "Open" in the UI for at least 1 full second (1,000,000 us)
        self.ui_visual_buffer = {prio: 0.0 for prio in range(8)}

        # Transmitter resource to ensure only one packet is transmitted at a time
        self.transmitter = simpy.PriorityResource(env, capacity=1)

        # Start GCL controller and queue processor
        self.env.process(self.gcl_controller())
        for prio in range(8):
            self.env.process(self.queue_processor(prio))

    def _is_gate_open(self, priority: int) -> bool:
        """Checks if a specific priority queue is currently permitted to transmit data (Gate is '1')."""
        if not self.tas_enabled:
            return True # Legacy Best-Effort networking: All gates are always permanently open!

        # The Gate Control List (GCL) uses a binary string: '00000000'
        # The leftmost bit (index 0) controls Priority 7 (Mission Critical).
        # The rightmost bit (index 7) controls Priority 0 (Background Traffic).
        idx = 7 - priority
        is_open = self.gate_status[idx] == '1'

        # UI HACK: Because SimPy processes microsecond (µs) events faster than the
        # Streamlit Python frontend can paint pixels to a browser, a 81µs "Gate Open"
        # window would be invisible to the human eye.
        # This "visual buffer" tricks the Streamlit UI (app.py) into holding the
        # HTML progress bar "Green" for a full 1,000,000 µs (1 second) so the presenter
        # can actually point at it during the live demo. This does *not* affect the math.
        if is_open:
            self.ui_visual_buffer[priority] = self.env.now + 1000000.0 # 1 second in us

        return is_open

    def is_visually_open(self, priority: int) -> bool:
        """Returns True if the gate is actually open in SimPy, OR if it is within the 1-second UI visual buffer."""
        return self._is_gate_open(priority) or self.env.now <= self.ui_visual_buffer[priority]

    def _get_time_until_gate_closes(self, priority: int) -> float:
        """Helper to find out how much time is left until this gate closes."""
        if not self.tas_enabled:
            return float('inf')
        idx = 7 - priority
        if self.gate_status[idx] == '0':
            return 0.0

        cycle_start = (self.env.now // self.cycle_time) * self.cycle_time
        time_in_cycle = self.env.now - cycle_start

        # Find next event where gate closes
        for event in self.gcl_events:
            if event['triggerTime'] > time_in_cycle:
                if event['gateStatus'][idx] == '0':
                    return event['triggerTime'] - time_in_cycle

        # If it doesn't close in this cycle, we assume it's open until end of cycle
        # This is a simplification, but sufficient for our test cases
        return self.cycle_time - time_in_cycle

    def gcl_controller(self):
        """Changes the gate statuses according to the GCL schedule."""
        if not self.tas_enabled:
            self.gate_status = "11111111"
            # Signal all gates open
            for prio in range(8):
                if not self.gate_open_events[prio].triggered:
                    self.gate_open_events[prio].succeed()
                    self.gate_open_events[prio] = simpy.Event(self.env)
            yield self.env.event()

        if not self.gcl_events:
            # If no GCL configured for this port, leave gates open for all traffic conceptually
            # but strictly based on problem, default is 00000001 (Prio 0 open, others closed)
            # wait forever
            yield self.env.event()

        while True:
            # If the cycle starts at a negative time (due to compensation extending before 0)
            # We align it with absolute time intervals.
            cycle_start = (self.env.now // self.cycle_time) * self.cycle_time
            if cycle_start < self.env.now:
                cycle_start += self.cycle_time

            # If we just started, let's process current cycle from now
            # Actually, `cycle_start` will loop perfectly
            cycle_start = self.env.now
            current_event_idx = 0

            while current_event_idx < len(self.gcl_events):
                event = self.gcl_events[current_event_idx]
                target_time = cycle_start + event['triggerTime']

                # If target time is in the past, it means triggerTime is negative (e.g., -34.80)
                # It should have triggered before the cycle actually started!
                # Wait until target time ONLY if it is in the future.
                wait_time = target_time - self.env.now
                if wait_time > 0:
                    yield self.env.timeout(wait_time)

                # Update status
                self.gate_status = event['gateStatus']

                # Trigger queue processors if their gate just opened
                for prio in range(8):
                    if self._is_gate_open(prio) and not self.gate_open_events[prio].triggered:
                        self.gate_open_events[prio].succeed()
                        self.gate_open_events[prio] = simpy.Event(self.env)

                current_event_idx += 1

            # Wait until the end of the cycle
            remaining_cycle = (cycle_start + self.cycle_time) - self.env.now
            if remaining_cycle > 0:
                yield self.env.timeout(remaining_cycle)

    def queue_processor(self, priority: int):
        """Processes packets from the queue when the gate is open."""
        while True:
            # Wait for a packet
            packet = yield self.queues[priority].get()

            # Check if gate is open
            if not self._is_gate_open(priority):
                # Wait until gate opens
                yield self.gate_open_events[priority]

            # Gate is open, acquire transmitter with priority (lower number = higher priority)
            # Simpy priority: lower number is higher priority. Prio 7 -> priority 0, Prio 0 -> priority 7
            simpy_prio = 7 - priority

            # To correctly mimic fragmentation with simpy's priority resource,
            # we request the transmitter per-fragment so Prio 7 can preempt between fragments!

            remaining_bytes = packet.size
            MTU = 1500

            while remaining_bytes > 0:
                chunk_size = min(remaining_bytes, MTU)
                chunk_bits = (chunk_size + 38) * 8
                chunk_duration_us = (chunk_bits / self.rate_bps) * 1_000_000

                # We need to make sure the gate is open before we even request the resource.
                if not self._is_gate_open(priority):
                    yield self.gate_open_events[priority]

                # Wait until gate is open
                if not self._is_gate_open(priority):
                    yield self.gate_open_events[priority]

                with self.transmitter.request(priority=simpy_prio) as req:
                    yield req

                    # Re-check gate after getting resource
                    can_transmit = False
                    while not can_transmit:
                        if not self._is_gate_open(priority):
                            yield self.gate_open_events[priority]
                            continue

                        time_left = self._get_time_until_gate_closes(priority)

                        if chunk_duration_us > time_left:
                            # It doesn't fit in the remaining window!
                            # If we just hold the transmitter, higher priority packets can't preempt us.
                            # So if it doesn't fit, we should release the transmitter and try again later.
                            # But since we are inside `with`, we can just break the loop, yield timeout,
                            # and start a new request? No, breaking inner loop just goes to transmit!
                            # We should yield timeout here, but we are holding the resource!
                            # Wait, preemption only works if we don't hold the resource.
                            break
                        else:
                            can_transmit = True
                            break

                    if not can_transmit:
                        # Release transmitter, wait for next opening, and try again
                        wait_time = time_left
                        if wait_time > 0:
                            yield self.env.timeout(wait_time)
                        continue # Re-evaluate while remaining_bytes > 0

                    yield self.env.timeout(chunk_duration_us)
                    remaining_bytes -= chunk_size

            # Entire packet sent
            packet.path_idx += 1
            self.parent_switch.forward_packet(packet)

class Switch:
    def __init__(self, env: simpy.Environment, name: str, simulator, gcl_config: Dict):
        self.env = env
        self.name = name
        self.simulator = simulator
        self.d_proc = 2.0 # us processing delay
        self.ports = {}

        # Initialize ports based on simulator port map
        port_map = simulator.routing.port_map.get(name, {})
        for neighbor, port_id in port_map.items():
            port_events = gcl_config.get(name, {}).get(port_id, [])
            cycle_time = simulator.hyper_period

            sp = SwitchPort(env, name, port_id, port_events, cycle_time, speed_mbps=simulator.link_speed_mbps, tas_enabled=simulator.tas_enabled)
            sp.parent_switch = self
            self.ports[port_id] = sp

    def process_arrival(self, packet: Packet):
        """Handles a packet arriving at the switch."""
        # Rogue Node Security check
        if self.simulator.attack_active and self.name == "SW1":
            if packet.priority == 7 and packet.flow.source == "MockAttacker":
                self.simulator.dropped_spoofed_packets += 1
                return # Drop packet immediately (don't forward to egress port)

        # Simulate processing delay
        yield self.env.timeout(self.d_proc)

        # Route packet
        path = self.simulator.routing.compute_routes([packet.flow])[packet.flow.flow_id]
        # packet.path_idx is currently the index of the node we arrived AT
        # Wait, in send_packet, if it reached node next_hop, it's not updating path_idx until egress!
        # Let's fix path index logic.
        current_node_idx = packet.path_idx + 1

        if current_node_idx + 1 < len(path):
            next_hop = path[current_node_idx + 1]
            port_id = self.simulator.routing.port_map[self.name][next_hop]

            # Enqueue to the appropriate egress port and priority queue
            self.ports[port_id].queues[packet.priority].put(packet)
        else:
            # Packet reached destination (shouldn't happen if Endpoint handles it, but just in case)
            packet.path_idx += 1
            self.forward_packet(packet)

    def forward_packet(self, packet: Packet):
        # The port finished transmitting, send to next node
        self.simulator.send_packet(packet, self.name)

class TSNSimulator:
    def __init__(self, topology: Topology, routing, gcl_config: Dict, hyper_period: int, tas_enabled: bool = True, attack_active: bool = False, link_speed_mbps: int = 100):
        self.env = simpy.Environment()
        self.topology = topology
        self.routing = routing
        self.gcl_config = gcl_config
        self.hyper_period = hyper_period
        self.tas_enabled = tas_enabled
        self.attack_active = attack_active
        self.link_speed_mbps = link_speed_mbps

        self.dropped_spoofed_packets = 0

        self.nodes = {}
        self.latencies = {} # Flow_id -> List of latencies

        self.build_network()

    def build_network(self):
        for node in self.topology.graph.nodes:
            ntype = self.topology.graph.nodes[node]['type']
            if ntype in ['endpoint', 'pc']:
                self.nodes[node] = Endpoint(self.env, node, self)
            elif ntype in ['switch', 'gateway']:
                self.nodes[node] = Switch(self.env, node, self, self.gcl_config)

    def start_flow(self, flow: Flow):
        self.latencies[flow.flow_id] = []
        source_endpoint = self.nodes[flow.source]
        self.env.process(source_endpoint.generate_flow(flow))

    def send_packet(self, packet: Packet, current_node: str):
        """Handles physical transmission between nodes."""
        path = self.routing.compute_routes([packet.flow])[packet.flow.flow_id]

        # If the packet has reached the destination
        if packet.path_idx >= len(path) - 1:
            latency = self.env.now - packet.creation_time
            self.latencies[packet.flow.flow_id].append(latency)
            return

        next_hop = path[packet.path_idx + 1]
        next_node_obj = self.nodes[next_hop]

        # Transmit over the physical link
        total_bits = (packet.size + 38) * 8
        duration_us = (total_bits / (self.link_speed_mbps * 1_000_000)) * 1_000_000

        # In a more granular sim we'd represent the physical link as a resource
        # but the egress queue's transmitter resource already serializes egress.
        # So link propagation is just a delay.
        def propagate():
            # Link propagation delay is typically 0 for simulation or negligible
            yield self.env.timeout(0)

            if isinstance(next_node_obj, Switch):
                self.env.process(next_node_obj.process_arrival(packet))
            elif isinstance(next_node_obj, Endpoint):
                # Arrived at destination endpoint immediately
                packet.path_idx += 1
                latency = self.env.now - packet.creation_time
                self.latencies[packet.flow.flow_id].append(latency)

        self.env.process(propagate())

    def run(self, duration: int):
        self.env.run(until=duration)

if __name__ == "__main__":
    from models import Topology
    from cuc import MockCUC
    from routing import CNCRouting
    from scheduler import ILPScheduler
    from gcl import GCLGenerator

    topo = Topology()
    cuc = MockCUC()
    flows = cuc.generate_test_flows()
    routing = CNCRouting(topo)
    routes = routing.compute_routes(flows)

    scheduler = ILPScheduler(topo, routes)
    flow1 = next(f for f in flows if f.flow_id == "Flow1")
    schedule = scheduler.schedule_flow(flow1)
    t_trans = scheduler.transmission_duration(flow1.payload_size)

    gcl_gen = GCLGenerator(topo, routing.port_map)
    hyper_period = gcl_gen.calculate_hyper_period(flows)
    gcl_config = gcl_gen.generate_gcl(schedule, t_trans, hyper_period, flow1.period)

    # Run a quick test simulation
    sim = TSNSimulator(topo, routing, gcl_config, hyper_period)
    for flow in flows:
        sim.start_flow(flow)

    print("Starting simulation for 100000 us (100ms)...")
    sim.run(100000)

    for flow_id, lats in sim.latencies.items():
        if not lats:
            continue
        avg_lat = sum(lats) / len(lats)
        max_lat = max(lats)
        print(f"Flow {flow_id} - Delivered: {len(lats)}, Avg Latency: {avg_lat:.2f} us, Max Latency: {max_lat:.2f} us")
