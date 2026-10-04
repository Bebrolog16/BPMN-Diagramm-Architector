import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from core.diagram import DiagramSDK
from core.exporter import BPMNExporter
from core.layout import LayoutEngine

NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}


def build_complex_scenario(output_path):
    sdk = DiagramSDK()
    customer_pool, customer_lanes = sdk.add_pool(
        sdk.ROOT_PROCESS_ID, ["Customer"], name="Customer"
    )
    store_pool, store_lanes = sdk.add_pool(
        sdk.ROOT_PROCESS_ID,
        ["Manager", "Warehouse", "Delivery"],
        name="Store",
    )

    customer_start = sdk.add_start_event("Order started", customer_lanes[0])
    order = sdk.add_user_task("Place order", customer_lanes[0])
    customer_end = sdk.add_end_event("Order submitted", customer_lanes[0])
    manager_start = sdk.add_start_event("Order received", store_lanes[0])
    verify = sdk.add_user_task("Verify order", store_lanes[0])
    decision = sdk.add_exclusive_gateway("Order valid?", store_lanes[0])
    correction = sdk.add_user_task("Correct details", store_lanes[0])
    warehouse_start = sdk.add_start_event("Preparation started", store_lanes[1])
    pick = sdk.add_task("Pick items", store_lanes[1])
    delivery_start = sdk.add_start_event("Dispatch started", store_lanes[2])
    ship = sdk.add_task("Ship order", store_lanes[2])
    store_end = sdk.add_end_event("Delivered", store_lanes[2])

    sdk.add_link(customer_start, order)
    sdk.add_link(order, customer_end)
    sdk.add_link(customer_end, manager_start, label="Order submitted")
    sdk.add_link(manager_start, verify)
    sdk.add_link(verify, decision)
    sdk.add_link(decision, correction, label="Needs correction", condition="invalid")
    sdk.add_link(correction, verify, label="Resubmitted")
    sdk.add_link(decision, warehouse_start, label="Approved", condition="valid")
    sdk.add_link(warehouse_start, pick)
    sdk.add_link(pick, delivery_start, label="Ready to ship")
    sdk.add_link(delivery_start, ship)
    sdk.add_link(ship, store_end)

    LayoutEngine(sdk.graph).calculate_layout()
    BPMNExporter(sdk.graph).export(str(output_path))
    return sdk


class TestComplexScenario(unittest.TestCase):
    def test_multiple_participants_lanes_and_decision_branches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "complex.bpmn"
            sdk = build_complex_scenario(output)
            root = ET.parse(output).getroot()
            self.assertEqual(len(root.findall(".//bpmn:participant", NS)), 3)
            self.assertEqual(len(root.findall(".//bpmn:lane", NS)), 4)
            self.assertGreaterEqual(len(root.findall(".//bpmn:sequenceFlow", NS)), 6)
            self.assertEqual(len(root.findall(".//bpmn:messageFlow", NS)), 1)
            self.assertEqual(len(sdk.graph.lane_bounds), 4)


if __name__ == "__main__":
    unittest.main()
