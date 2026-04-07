"""
Centralized Network Configuration (CNC) Routing Module

This module represents the "Control Plane" of the SD-TSN architecture.
It calculates the exact physical path (routing) that each data flow will take
through the zonal topology and generates the Layer 2 (L2) MAC lookup tables
that will be flashed to the network switches.
"""

from typing import List, Dict, Any
import networkx as nx
from models import Topology, Flow
import json

class CNCRouting:
    """
    Computes shortest-path routes through the NetworkX topology and translates
    those routes into hardware-level concepts (MAC addresses, egress port IDs,
    and L2 forwarding rules).
    """
    def __init__(self, topology: Topology):
        self.topology = topology
        self.mac_table: Dict[str, str] = self._assign_mac_addresses()
        self.port_map: Dict[str, Dict[str, int]] = self._assign_ports()

    def _assign_mac_addresses(self) -> Dict[str, str]:
        """Assigns dummy MAC addresses to endpoints and the PC."""
        macs = {}
        nodes = self.topology.graph.nodes(data=True)
        mac_idx = 1
        for node, data in nodes:
            if data['type'] in ['endpoint', 'pc', 'gateway']:
                macs[node] = f"00:00:00:00:00:{mac_idx:02x}"
                mac_idx += 1
        return macs

    def _assign_ports(self) -> Dict[str, Dict[str, int]]:
        """Assigns simple integer IDs for switch/node egress ports."""
        port_map = {}
        for node in self.topology.graph.nodes:
            port_map[node] = {}
            neighbors = list(self.topology.graph.successors(node))
            for i, neighbor in enumerate(neighbors, start=1):
                port_map[node][neighbor] = i
        return port_map

    def compute_routes(self, flows: List[Flow]) -> Dict[str, List[str]]:
        """
        Computes the shortest physical path through the network for each flow.
        Uses NetworkX Dijkstra's algorithm to find the optimal route from source to destination.

        Example: If Flow 1 is E1 -> E3, this checks the graph and might return:
        ['E1', 'SW1', 'GW', 'SW4', 'E3']
        """
        routes = {}
        for flow in flows:
            path = self.topology.get_shortest_path(flow.source, flow.destination)
            routes[flow.flow_id] = path
        return routes

    def generate_l2_lookup_tables(self, flows: List[Flow]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generates L2 lookup table entries for each node mimicking standard YANG hardware models.

        In simple terms: It tells each switch "If you receive a packet with Destination MAC X
        on Ingress Port Y, forward it out Egress Port Z".
        """
        routes = self.compute_routes(flows)
        l2_tables = {node: [] for node in self.topology.graph.nodes}

        # We index the entries per node to mirror YANG L2 Lookup Table schema:
        # L2 Lookup Table entries: Include index, macaddr, srcport, vlanid, and destport.
        entry_indices = {node: 1 for node in self.topology.graph.nodes}

        for flow in flows:
            path = routes[flow.flow_id]
            dest_mac = self.mac_table[flow.destination]
            vlan_id = flow.priority # Map VLAN ID to priority for simplicity, or just a constant

            for i in range(len(path) - 1):
                current_node = path[i]
                next_node = path[i+1]

                # Ingress port: If it's the source, it's generated internally, so srcport might be 0 or conceptually "internal".
                # For switches, we can find the port from the previous node.
                if i == 0:
                    src_port = 0 # internal ingress
                else:
                    prev_node = path[i-1]
                    # The port on `current_node` that connects from `prev_node`
                    # In a real switch, ingress port is where it arrived.
                    # We can use the reverse mapping for ingress port on current node.
                    src_port = self.port_map[current_node].get(prev_node, 0)

                dest_port = self.port_map[current_node][next_node]

                entry = {
                    "index": entry_indices[current_node],
                    "macaddr": dest_mac,
                    "srcport": src_port,
                    "vlanid": vlan_id,
                    "destport": dest_port
                }

                # Check if this rule already exists (for same dest & vlan) to avoid duplicates
                duplicate = any(
                    e['macaddr'] == dest_mac and e['vlanid'] == vlan_id and e['destport'] == dest_port
                    for e in l2_tables[current_node]
                )
                if not duplicate:
                    l2_tables[current_node].append(entry)
                    entry_indices[current_node] += 1

        return l2_tables

if __name__ == '__main__':
    from cuc import MockCUC
    topo = Topology()
    cuc = MockCUC()
    flows = cuc.generate_test_flows()

    routing = CNCRouting(topo)
    routes = routing.compute_routes(flows)

    print("Routes:")
    for f_id, path in routes.items():
        print(f"{f_id}: {' -> '.join(path)}")

    print("\nMAC Addresses:")
    print(json.dumps(routing.mac_table, indent=2))

    print("\nPort Map (Node -> {Neighbor: Port}):")
    print(json.dumps(routing.port_map, indent=2))

    print("\nL2 Lookup Tables:")
    l2_tables = routing.generate_l2_lookup_tables(flows)
    print(json.dumps(l2_tables, indent=2))
