import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from core.diagram import DiagramSDK
from core.exporter import BPMNExporter
from core.layout import LayoutEngine

NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
}


class TestBPMNSystem(unittest.TestCase):
    def setUp(self):
        self.sdk = DiagramSDK()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_file = Path(self.temp_dir.name) / "result.bpmn"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_multiple_participants_and_lane_names_are_preserved(self):
        _, customer_lanes = self.sdk.add_pool(
            self.sdk.ROOT_PROCESS_ID, ["Customer"], name="Customer"
        )
        _, operator_lanes = self.sdk.add_pool(
            self.sdk.ROOT_PROCESS_ID, ["Operator", "Warehouse"], name="Store"
        )
        customer_start = self.sdk.add_start_event("Customer starts", customer_lanes[0])
        request = self.sdk.add_user_task("Place order", customer_lanes[0])
        operator_start = self.sdk.add_start_event("Store receives", operator_lanes[0])
        approve = self.sdk.add_user_task("Approve", operator_lanes[0])
        self.sdk.add_link(customer_start, request)
        self.sdk.add_link(request, operator_start, label="Order sent")
        self.sdk.add_link(operator_start, approve)

        self.assertEqual(len(self.sdk.graph.pools), 2)
        self.assertEqual([lane.name for lane in self.sdk.graph.lanes.values()], ["Customer", "Operator", "Warehouse"])
        self.assertEqual([edge.flow_type for edge in self.sdk.graph.edges], ["sequence", "message", "sequence"])

    def test_layout_centers_nodes_and_keeps_lanes_separate(self):
        _, lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["Lane 1", "Lane 2"])
        first = self.sdk.add_task("First", lanes[0])
        second = self.sdk.add_task("Second", lanes[0])
        other_lane = self.sdk.add_task("Other lane", lanes[1])
        self.sdk.add_link(self.sdk.ROOT_START_TASK_ID, first)
        self.sdk.add_link(first, second)

        layout = LayoutEngine(self.sdk.graph)
        layout.calculate_layout()

        start = self.sdk.graph.nodes[self.sdk.ROOT_START_TASK_ID]
        self.assertEqual(start.coords[0] + start.width / 2, layout.START_X)
        self.assertGreater(self.sdk.graph.nodes[second].coords[0], self.sdk.graph.nodes[first].coords[0])
        self.assertLess(self.sdk.graph.nodes[first].coords[1], self.sdk.graph.nodes[other_lane].coords[1])
        for lane_id, bounds in self.sdk.graph.lane_bounds.items():
            y, height = bounds[1], bounds[3]
            lane_nodes = [n for n in self.sdk.graph.nodes.values() if n.parent_id == lane_id]
            self.assertTrue(all(n.coords[1] >= y and n.coords[1] + n.height <= y + height for n in lane_nodes))

    def test_parallel_gateway_branches_use_separate_route_tracks(self):
        gateway = self.sdk.add_parallel_gateway("Split", self.sdk.ROOT_PROCESS_ID)
        tasks = [
            self.sdk.add_task(f"Branch {index}", self.sdk.ROOT_PROCESS_ID)
            for index in range(4)
        ]
        self.sdk.add_link(self.sdk.ROOT_START_TASK_ID, gateway)
        for task in tasks:
            self.sdk.add_link(gateway, task)

        LayoutEngine(self.sdk.graph).calculate_layout()
        exporter = BPMNExporter(self.sdk.graph)
        routes = [
            exporter._route_edge(edge, index)
            for index, edge in enumerate(self.sdk.graph.edges)
            if edge.source == gateway
        ]
        route_tracks = [route[1][0] for route in routes]

        self.assertEqual(len(routes), 4)
        self.assertEqual(len(set(route_tracks)), 4)

    def test_export_has_participant_and_lane_shapes_and_typed_flows(self):
        _, customer_lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["Customer"], name="Customer")
        _, store_lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["Manager", "Warehouse"], name="Store")
        start = self.sdk.add_start_event("Start", customer_lanes[0])
        request = self.sdk.add_user_task("Send request", customer_lanes[0])
        decision = self.sdk.add_exclusive_gateway("Approved?", store_lanes[0])
        approved = self.sdk.add_task("Continue", store_lanes[1])
        rejected = self.sdk.add_end_event("Return", store_lanes[0])
        self.sdk.add_link(start, request)
        self.sdk.add_link(request, decision, label="Request received")
        self.sdk.add_link(decision, approved, label="Yes", condition="approved")
        self.sdk.add_link(decision, rejected, label="No", condition="not approved")

        LayoutEngine(self.sdk.graph).calculate_layout()
        BPMNExporter(self.sdk.graph).export(str(self.output_file))
        root = ET.parse(self.output_file).getroot()

        participants = root.findall(".//bpmn:participant", NS)
        lanes = root.findall(".//bpmn:lane", NS)
        self.assertEqual(len(participants), 3)  # Root process plus two participants.
        self.assertEqual([lane.get("name") for lane in lanes], ["Customer", "Manager", "Warehouse"])
        participant_ids = {p.get("id") for p in participants}
        shape_refs = {
            shape.get("bpmnElement")
            for shape in root.findall(".//bpmndi:BPMNShape", NS)
        }
        self.assertTrue(participant_ids.issubset(shape_refs))
        self.assertTrue({lane.get("id") for lane in lanes}.issubset(shape_refs))
        self.assertEqual(len(root.findall(".//bpmn:sequenceFlow", NS)), 3)
        self.assertEqual(len(root.findall(".//bpmn:messageFlow", NS)), 1)
        conditions = root.findall(".//bpmn:conditionExpression", NS)
        self.assertEqual([condition.text for condition in conditions], ["approved", "not approved"])
        diagram_edges = root.findall(".//bpmndi:BPMNEdge", NS)
        self.assertEqual(len(diagram_edges), 4)
        self.assertTrue(all(len(edge.findall("di:waypoint", NS)) >= 2 for edge in diagram_edges))

    def test_export_rejects_missing_layout(self):
        with self.assertRaises((ValueError, TypeError)):
            BPMNExporter(self.sdk.graph).export(str(self.output_file))


if __name__ == "__main__":
    unittest.main()
