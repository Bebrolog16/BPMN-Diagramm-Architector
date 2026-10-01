import tempfile
import unittest
from pathlib import Path

from core.executor import CodeExecutor


VALID_CODE = '''
sdk = DiagramSDK()
task = sdk.add_task("Review request", sdk.ROOT_PROCESS_ID)
sdk.add_link(sdk.ROOT_START_TASK_ID, task)
sdk.add_link(task, sdk.ROOT_END_TASK_ID)
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("ignored-by-runtime.bpmn")
'''


class TestCodeExecutor(unittest.TestCase):
    def test_executes_only_supported_sdk_program(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diagram.bpmn"
            result = CodeExecutor(str(output)).execute(VALID_CODE)
            self.assertTrue(result["success"], result["error"])
            self.assertTrue(output.is_file())
            self.assertIn("BPMNDiagram", output.read_text(encoding="utf-8"))

    def test_supports_list_indexing_used_for_lane_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diagram.bpmn"
            code = '''
sdk = DiagramSDK()
pool_id, lanes = sdk.add_pool(sdk.ROOT_PROCESS_ID, ["Customer", "Manager"])
task = sdk.add_task("Review", lanes[1])
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("ignored.bpmn")
'''
            result = CodeExecutor(str(output)).execute(code)
            self.assertTrue(result["success"], result["error"])
            self.assertTrue(output.is_file())

    def test_rejects_indexing_non_sequence_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diagram.bpmn"
            code = '''
sdk = DiagramSDK()
task = sdk.add_task("Review", sdk.ROOT_PROCESS_ID[0])
'''
            result = CodeExecutor(str(output)).execute(code)
            self.assertFalse(result["success"])
            self.assertIn("Indexing is allowed only for lists and tuples", result["error"])

    def test_rejects_imports_and_arbitrary_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diagram.bpmn"
            code = 'import os\nopen("outside.txt", "w")'
            result = CodeExecutor(str(output)).execute(code)
            self.assertFalse(result["success"])
            self.assertFalse(output.exists())

    def test_rejects_unsupported_statements(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "diagram.bpmn"
            result = CodeExecutor(str(output)).execute("while True: pass")
            self.assertFalse(result["success"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
