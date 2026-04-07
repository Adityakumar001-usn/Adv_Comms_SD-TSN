"""
Centralized User Configuration (CUC) Mock Module

In a true SD-TSN architecture, the CUC receives requests from endpoints
(like sensors or cameras) to set up data streams, and it forwards these requirements
to the Centralized Network Configuration (CNC) controller.

This mock module simulates that behavior by statically generating the test flows
required to validate the mathematical determinism of the network.
"""

from models import Flow

class MockCUC:
    """
    Simulates the Centralized User Configuration endpoint.
    Generates two specific flows: one mission-critical (Priority 7) and one
    best-effort background interference (Priority 0).
    """
    def __init__(self):
        self.flows = []

    def generate_test_flows(self):
        """
        Creates and returns the list of Flow objects for the simulation test suite.
        """
        # Flow 1 (Time-Sensitive): Mission Critical (e.g., LiDAR or electronic steering control)
        # This flow must strictly maintain a <= 500 us latency boundary.
        # It's given Priority 7 (the highest IEEE 802.1Q priority) to ensure it gets scheduled perfectly.
        flow1 = Flow(
            flow_id="Flow1",
            source="E1",
            destination="E3",
            period=50000,          # 50 ms = 50000 us
            priority=7,
            payload_size=1024,
            max_latency=500        # 500 us
        )

        # Flow 2 (Interference): E2 to E3, Priority 0, 10ms period, variable payload (3200 to 102400 Bytes).
        # We define a base payload for generation; actual simulations will vary it.
        # It's given Priority 0 (Best-Effort). This is the "Delivery Truck" traffic that we must prevent
        # from blocking the Priority 7 "Ambulance" traffic.
        flow2 = Flow(
            flow_id="Flow2",
            source="E2",
            destination="E3",
            period=10000,          # 10 ms = 10000 us
            priority=0,
            payload_size=3200,     # Placeholder, simulation iterates through payload sizes
            max_latency=0          # No strict max latency for best effort
        )

        self.flows = [flow1, flow2]
        return self.flows

if __name__ == '__main__':
    cuc = MockCUC()
    flows = cuc.generate_test_flows()
    for f in flows:
        print(f)
