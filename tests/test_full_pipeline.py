import unittest
import os
import sys

# MAGIC FIX: Add project root to sys.path
# This allows 'from core.xxx import yyy' to work regardless of where the test is run from
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.diagram import DiagramSDK
from core.layout import LayoutEngine
from core.exporter import BPMNExporter

class TestBPMNSystem(unittest.TestCase):
    def setUp(self):
        self.sdk = DiagramSDK()
        self.output_file = "tests/test_result.bpmn"

    def test_graph_construction(self):
        """Test 1: Check if nodes and links are correctly added to the graph"""
        print("\nTesting Graph Construction...")
        pool_id, lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["User", "Admin"])
        t1 = self.sdk.add_task("Task 1", lanes[0])
        t2 = self.sdk.add_task("Task 2", lanes[1])
        self.sdk.add_link(self.sdk.ROOT_START_TASK_ID, t1)
        self.sdk.add_link(t1, t2)
        self.sdk.add_link(t2, self.sdk.ROOT_END_TASK_ID)

        # Verify nodes exist
        self.assertIn(t1, self.sdk.graph.nodes)
        self.assertIn(t2, self.sdk.graph.nodes)
        # Verify edges exist
        self.assertEqual(len(self.sdk.graph.edges), 3)
        print("Graph Construction: OK, блядь")

    def test_layout_logic(self):
        """Test 2: Check if coordinates are actually calculated and differ"""
        print("\nTesting Layout Engine...")
        pool_id, lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["Lane 1"])
        t1 = self.sdk.add_task("T1", lanes[0])
        t2 = self.sdk.add_task("T2", lanes[0])
        self.sdk.add_link(self.sdk.ROOT_START_TASK_ID, t1)
        self.sdk.add_link(t1, t2)

        layout = LayoutEngine(self.sdk.graph)
        layout.calculate_layout()

        # Start node X coordinate should be START_X - (width/2) = 100.0 - 18.0 = 82.0
        self.assertEqual(self.sdk.graph.nodes[self.sdk.ROOT_START_TASK_ID].coords[0], 82.0)
        # T1 should be to the right of start
        self.assertGreater(self.sdk.graph.nodes[t1].coords[0], 100.0)
        # T2 should be to the right of T1
        self.assertGreater(self.sdk.graph.nodes[t2].coords[0], self.sdk.graph.nodes[t1].coords[0])
        print("Layout Logic: OK, ваааа мать ебал жи есть внатуре сук")

    def test_exporter_output(self):
        """Test 3: Check if XML file is generated and contains key BPMN tags"""
        print("\nTesting Exporter...")
        pool_id, lanes = self.sdk.add_pool(self.sdk.ROOT_PROCESS_ID, ["Test Lane"])
        t1 = self.sdk.add_task("Export Task", lanes[0])
        self.sdk.add_link(self.sdk.ROOT_START_TASK_ID, t1)
        self.sdk.add_link(t1, self.sdk.ROOT_END_TASK_ID)

        layout = LayoutEngine(self.sdk.graph)
        layout.calculate_layout()

        exporter = BPMNExporter(self.sdk.graph)
        exporter.export(self.output_file)

        # Verify file exists
        self.assertTrue(os.path.exists(self.output_file))
        
        with open(self.output_file, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("bpmn:definitions", content)
            self.assertIn("bpmndi:BPMNDiagram", content)
            self.assertIn("Export Task", content)
        
        print("Exporter Output: OK, блядь")

if __name__ == "__main__":
    unittest.main()
