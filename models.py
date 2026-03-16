import networkx as nx
from dataclasses import dataclass
from typing import Optional

@dataclass
class Flow:
    flow_id: str
    source: str
    destination: str
    period: int  # in microseconds (us)
    priority: int
    payload_size: int  # in bytes
    max_latency: int  # in microseconds (us)

class Topology:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.build_topology()

    def add_bidirectional_link(self, node1: str, node2: str, speed_mbps: int = 100):
        self.graph.add_edge(node1, node2, speed=speed_mbps)
        self.graph.add_edge(node2, node1, speed=speed_mbps)

    def build_topology(self):
        # Add nodes
        endpoints = ['E1', 'E2', 'E3']
        switches = ['SW1', 'SW2', 'SW3', 'SW4']
        gateway = 'GW'
        pc = 'PC'

        self.graph.add_nodes_from(endpoints, type='endpoint')
        self.graph.add_nodes_from(switches, type='switch')
        self.graph.add_node(gateway, type='gateway')
        self.graph.add_node(pc, type='pc')

        # Add links based on requirements
        # E1 and E2 connect to SW1
        self.add_bidirectional_link('E1', 'SW1')
        self.add_bidirectional_link('E2', 'SW1')

        # E3 connects to SW4
        self.add_bidirectional_link('E3', 'SW4')

        # GW connects directly to SW1, SW2, SW3, SW4, and PC
        self.add_bidirectional_link('GW', 'SW1')
        self.add_bidirectional_link('GW', 'SW2')
        self.add_bidirectional_link('GW', 'SW3')
        self.add_bidirectional_link('GW', 'SW4')
        self.add_bidirectional_link('GW', 'PC')

        # Switches form a ring around gateway: SW1 connects to SW2 and SW3; SW4 connects to SW2 and SW3
        self.add_bidirectional_link('SW1', 'SW2')
        self.add_bidirectional_link('SW1', 'SW3')
        self.add_bidirectional_link('SW4', 'SW2')
        self.add_bidirectional_link('SW4', 'SW3')

    def get_shortest_path(self, source: str, destination: str) -> list[str]:
        return nx.shortest_path(self.graph, source=source, target=destination)

if __name__ == '__main__':
    topo = Topology()
    print("Nodes:", topo.graph.nodes(data=True))
    print("Edges:", topo.graph.edges(data=True))
    print("Path E1 to E3:", topo.get_shortest_path('E1', 'E3'))
