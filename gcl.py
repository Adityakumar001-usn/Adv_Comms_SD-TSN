"""
Gate Control List (GCL) Configuration Module

This module takes the exact µs-level offsets calculated by the ILP Scheduler
and turns them into IEEE 802.1Qbv Time-Aware Shaper (TAS) configurations.
It determines exactly when network switch queues should open and close,
enforcing the crucial "Guard Band" before critical data arrives.
It exports these configurations into a standard YANG-style XML format.
"""

import math
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Dict, Tuple, Any
from models import Flow, Topology

class GCLGenerator:
    """
    Generates deterministic schedules for every egress port queue in the network.
    """
    def __init__(self, topology: Topology, port_map: Dict[str, Dict[str, int]]):
        self.topology = topology
        self.port_map = port_map
        self.guard_band = 121.76  # us
        self.compensation = 1.0   # us

    def calculate_hyper_period(self, flows: List[Flow]) -> int:
        """Calculates the network-wide hyper-period (LCM of all flow periods)."""
        periods = [flow.period for flow in flows]
        # LCM of multiple numbers
        lcm = periods[0]
        for p in periods[1:]:
            lcm = abs(lcm * p) // math.gcd(lcm, p)
        return lcm

    def generate_gcl(self, schedule: Dict[Tuple[str, str], float], t_trans: float, hyper_period: int, flow_period: int) -> Dict[str, Dict[int, List[Dict[str, Any]]]]:
        """
        Generates exact open/close timings (GCL) for each switch egress port for Priority 7 and 0 queues.
        Returns a mapping of Node -> Port -> List of Gate Events.
        """
        # Node -> Port -> Event List
        gcl_config = {node: {} for node in self.topology.graph.nodes if self.topology.graph.nodes[node]['type'] in ['switch', 'gateway']}

        # We need to construct events over the hyper_period.
        # Since Flow 1 is Priority 7, we iterate over every instance of Flow 1 within the hyper_period.
        num_instances = hyper_period // flow_period

        for edge, offset in schedule.items():
            src_node, dst_node = edge
            # Endpoints don't enforce GCL in this context, only switches/gateways
            if self.topology.graph.nodes[src_node]['type'] not in ['switch', 'gateway']:
                continue

            port = self.port_map[src_node][dst_node]
            if port not in gcl_config[src_node]:
                gcl_config[src_node][port] = []

            for i in range(num_instances):
                # The precise transmission window for Priority 7
                # Window starts at offset - C
                # Window ends at offset + t_trans + C
                base_time = i * flow_period
                start_p7 = base_time + offset - self.compensation
                end_p7 = base_time + offset + t_trans + self.compensation

                # The Guard Band precedes the Priority 7 window
                start_gb = start_p7 - self.guard_band

                # Event 1: Start of Guard Band.
                # Priority 0 gate closes to prevent interference. Priority 7 remains closed (or closes).

                # We simply record the exact times, avoiding wrap-around.
                # Since Flow 1 periods are exactly synchronized with the hyper_period in our test,
                # we just need to ensure the times are non-negative or we offset them globally.
                # But actually, start_gb CAN be negative for the very first period at time 0!
                # If start_gb < 0, it means it should have started BEFORE time 0.
                # To keep it simple, if start_gb < 0, we just set it to 0.

                _start_gb = max(0, start_gb)
                _start_p7 = max(0, start_p7)
                _end_p7 = max(0, end_p7)

                # Note: We append for EVERY instance of the flow in the hyper_period.
                # The simulator should reset to 0 after hyper_period.

                gcl_config[src_node][port].append({
                    'triggerTime': _start_gb,
                    'gateStatus': '00000000' # All gates closed
                })

                # Event 2: Start of Priority 7 window.
                gcl_config[src_node][port].append({
                    'triggerTime': _start_p7,
                    'gateStatus': '10000000' # Prio 7 open
                })

                # Event 3: End of Priority 7 window.
                gcl_config[src_node][port].append({
                    'triggerTime': _end_p7,
                    'gateStatus': '00000001' # Prio 0 open
                })

        # Sort the events by triggerTime for each port
        for node, ports in gcl_config.items():
            for port in ports:
                ports[port] = sorted(ports[port], key=lambda e: e['triggerTime'])

                # Check if we need to insert an initial state event at time 0
                # if the first event doesn't start at 0
                if ports[port] and ports[port][0]['triggerTime'] > 0:
                    ports[port].insert(0, {
                        'triggerTime': 0.0,
                        'gateStatus': '00000001' # Prio 0 open
                    })

        return gcl_config

    def generate_xml_configuration(self, l2_tables: Dict[str, List[Dict[str, Any]]], gcl_config: Dict[str, Dict[int, List[Dict[str, Any]]]], hyper_period: int) -> str:
        """
        Generates the structured XML file mimicking a YANG model for L2 Lookup Tables and TAS Configurations.
        """
        root = ET.Element('network-configuration')

        # Create elements per node
        for node in self.topology.graph.nodes:
            # We only configure switches and gateway
            if self.topology.graph.nodes[node]['type'] not in ['switch', 'gateway']:
                continue

            node_elem = ET.SubElement(root, 'node')
            node_elem.set('id', node)

            # --- L2 Lookup Table Configuration ---
            l2_lookup_elem = ET.SubElement(node_elem, 'l2-lookup-table')
            if node in l2_tables:
                for entry in l2_tables[node]:
                    entry_elem = ET.SubElement(l2_lookup_elem, 'entry')
                    ET.SubElement(entry_elem, 'index').text = str(entry['index'])
                    ET.SubElement(entry_elem, 'macaddr').text = entry['macaddr']
                    ET.SubElement(entry_elem, 'srcport').text = str(entry['srcport'])
                    ET.SubElement(entry_elem, 'vlanid').text = str(entry['vlanid'])
                    ET.SubElement(entry_elem, 'destport').text = str(entry['destport'])

            # --- TAS Configuration ---
            tas_config_elem = ET.SubElement(node_elem, 'tas-configuration')

            if node in gcl_config:
                for port, events in gcl_config[node].items():
                    port_elem = ET.SubElement(tas_config_elem, 'port')
                    port_elem.set('id', str(port))

                    ET.SubElement(port_elem, 'BaseTime').text = "0"
                    ET.SubElement(port_elem, 'cycleTime').text = str(hyper_period)
                    ET.SubElement(port_elem, 'cycleTimeExtension').text = "0"
                    ET.SubElement(port_elem, 'controlListLength').text = str(len(events))

                    # Initial state (before any events): Prio 0 is open, others closed.
                    # Unless the first event starts at time 0.
                    initial_state = '00000001'
                    ET.SubElement(port_elem, 'initialGateStatus').text = initial_state

                    for idx, event in enumerate(events, start=1):
                        schedule_entry_elem = ET.SubElement(port_elem, 'tasScheduleEntry')
                        ET.SubElement(schedule_entry_elem, 'index').text = str(idx)
                        ET.SubElement(schedule_entry_elem, 'triggerTime').text = f"{event['triggerTime']:.2f}"
                        ET.SubElement(schedule_entry_elem, 'gateStatus').text = event['gateStatus']

        # Pretty print XML
        xml_str = ET.tostring(root, encoding='utf-8')
        parsed_xml = minidom.parseString(xml_str)
        pretty_xml = parsed_xml.toprettyxml(indent="  ")

        # Explicitly write the generated XML to the artifact file
        with open("network_config.xml", "w") as f:
            f.write(pretty_xml)

        return pretty_xml

if __name__ == "__main__":
    from models import Topology
    from cuc import MockCUC
    from routing import CNCRouting
    from scheduler import ILPScheduler
    import json
    import os

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

    print(f"Hyper-period: {hyper_period} us")

    gcl_config = gcl_gen.generate_gcl(schedule, t_trans, hyper_period, flow1.period)

    # Generate L2 tables
    l2_tables = routing.generate_l2_lookup_tables(flows)

    # Generate XML
    xml_output = gcl_gen.generate_xml_configuration(l2_tables, gcl_config, hyper_period)

    with open("network_config.xml", "w") as f:
        f.write(xml_output)

    print(f"Generated XML Configuration saved to network_config.xml")

    # Dump a tiny sample to verify
    for line in xml_output.split('\n')[:40]:
        print(line)
