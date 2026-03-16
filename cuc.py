from models import Flow

class MockCUC:
    """
    Mock Centralized User Configuration (CUC) module that generates test flows.
    """
    def __init__(self):
        self.flows = []

    def generate_test_flows(self):
        # Flow 1 (Time-Sensitive): E1 to E3, Priority 7, 50ms period, 1024 Byte payload, 500µs max latency.
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
