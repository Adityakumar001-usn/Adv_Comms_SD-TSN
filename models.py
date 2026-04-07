"""
Data Models for SD-TSN In-Vehicle Network Simulation

This module defines the foundational structures for the simulation:
1. `Flow`: Represents a data stream (either mission-critical or best-effort interference).
2. `Topology`: A NetworkX directed graph representing the physical wiring of the zonal automotive architecture.
"""

import networkx as nx
from dataclasses import dataclass
from typing import Optional

@dataclass
class Flow:
    """
    Represents a periodic network transmission from a source endpoint to a destination endpoint.

    Attributes:
        flow_id: A unique identifier (e.g., "Flow1").
        source: The originating node (e.g., "E1").
        destination: The target node (e.g., "E3").
        period: How often the flow transmits data (in microseconds).
        priority: IEEE 802.1Q PCP priority level (0 = Best Effort, 7 = Time-Sensitive Critical).
        payload_size: Size of the data packet in Bytes.
        max_latency: The strict deadline (in microseconds) the packet must arrive by.
    """
    flow_id: str
    source: str
    destination: str
    period: int  # in microseconds (us)
    priority: int
    payload_size: int  # in bytes
    max_latency: int  # in microseconds (us)

class Topology:
    """
    Constructs the physical network architecture using a NetworkX directed graph.
    All physical links are modeled as full-duplex 100 Mbps automotive Ethernet connections.
    """
    def __init__(self, expand_topology: bool = False, link_speed_mbps: int = 100):
        self.expand_topology = expand_topology
        self.link_speed_mbps = link_speed_mbps
        self.graph = nx.DiGraph()
        self.build_topology()

    def add_bidirectional_link(self, node1: str, node2: str, speed_mbps: int = 100):
        self.graph.add_edge(node1, node2, speed=speed_mbps)
        self.graph.add_edge(node2, node1, speed=speed_mbps)

    def build_topology(self):
        # Add nodes
        endpoints = ['E1', 'E2', 'E3']
        switches = ['SW1', 'SW2', 'SW3', 'SW4']

        if self.expand_topology:
            endpoints.append('E4')
            switches.append('SW5')
        gateway = 'GW'
        pc = 'PC'

        self.graph.add_nodes_from(endpoints, type='endpoint')
        self.graph.add_nodes_from(switches, type='switch')
        self.graph.add_node(gateway, type='gateway')
        self.graph.add_node(pc, type='pc')

        # Add links based on requirements
        # E1 and E2 connect to SW1
        self.add_bidirectional_link('E1', 'SW1', self.link_speed_mbps)
        self.add_bidirectional_link('E2', 'SW1', self.link_speed_mbps)

        # E3 connects to SW4
        self.add_bidirectional_link('E3', 'SW4', self.link_speed_mbps)

        # GW connects directly to SW1, SW2, SW3, SW4, and PC
        self.add_bidirectional_link('GW', 'SW1', self.link_speed_mbps)
        self.add_bidirectional_link('GW', 'SW2', self.link_speed_mbps)
        self.add_bidirectional_link('GW', 'SW3', self.link_speed_mbps)
        self.add_bidirectional_link('GW', 'SW4', self.link_speed_mbps)
        self.add_bidirectional_link('GW', 'PC', self.link_speed_mbps)

        # Core Architecture: Switches form a redundant ring around the Central Gateway
        # This mirrors modern Zonal Automotive architectures where SW1 might be the "Front Left Zone"
        # and SW4 might be the "Rear Right Zone".
        self.add_bidirectional_link('SW1', 'SW2', self.link_speed_mbps)
        self.add_bidirectional_link('SW1', 'SW3', self.link_speed_mbps)
        self.add_bidirectional_link('SW4', 'SW2', self.link_speed_mbps)
        self.add_bidirectional_link('SW4', 'SW3', self.link_speed_mbps)

        if self.expand_topology:
            # Dynamic UI Expansion: Simulates adding a new "Trailer Zone" or "Roof Sensor Zone" (SW5)
            # and a new endpoint (E4) to test if the routing algorithms adapt instantly.
            self.add_bidirectional_link('SW4', 'SW5', self.link_speed_mbps)
            self.add_bidirectional_link('SW5', 'E4', self.link_speed_mbps)

    def get_shortest_path(self, source: str, destination: str) -> list[str]:
        return nx.shortest_path(self.graph, source=source, target=destination)

if __name__ == '__main__':
    topo = Topology()
    print("Nodes:", topo.graph.nodes(data=True))
    print("Edges:", topo.graph.edges(data=True))
    print("Path E1 to E3:", topo.get_shortest_path('E1', 'E3'))
