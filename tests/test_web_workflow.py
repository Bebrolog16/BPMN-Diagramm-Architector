import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import storage
from web import app as web_app


VALID_CODE = '''
sdk = DiagramSDK()
task = sdk.add_task("Review", sdk.ROOT_PROCESS_ID)
sdk.add_link(sdk.ROOT_START_TASK_ID, task)
sdk.add_link(task, sdk.ROOT_END_TASK_ID)
layout = LayoutEngine(sdk.graph)
layout.calculate_layout()
exporter = BPMNExporter(sdk.graph)
exporter.export("runtime-selected.bpmn")
'''


class FakeOllama:
    def __init__(self, **_kwargs):
        pass

    def generate_plan(self, *_args, **_kwargs):
        return "1. Add a review task. 2. Connect it to the existing process."

    def generate_code(self, *_args, **_kwargs):
        return VALID_CODE

    @staticmethod
    def clean_code(code):
        return code


class TestWebWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_database = storage.DATABASE_FILE
        self.old_generated_dir = web_app.GENERATED_DIR
        storage.DATABASE_FILE = str(Path(self.temp_dir.name) / "history.sqlite3")
        web_app.GENERATED_DIR = str(Path(self.temp_dir.name) / "generated")
        storage.init_storage()
        self.user = storage.create_user("workflow", "workflow-password", "Workflow")

    def tearDown(self):
        storage.DATABASE_FILE = self.old_database
        web_app.GENERATED_DIR = self.old_generated_dir
        self.temp_dir.cleanup()

    @patch("web.app.OllamaBPMNClient", FakeOllama)
    def test_plan_approval_creates_and_restores_a_persistent_revision(self):
        session = web_app.create_session(user=self.user)
        session_id = session["session_id"]
        plan = web_app.plan_change(session_id, web_app.TextRequest(text="Add review"), user=self.user)
        applied = web_app.apply_plan(session_id, web_app.ApplyRequest(plan_id=plan["plan_id"]), user=self.user)

        self.assertIn("BPMNDiagram", applied["xml"])
        self.assertEqual(storage.get_session(session_id)["current_revision_id"], applied["revision_id"])
        history = web_app.read_session(session_id, user=self.user)
        self.assertEqual(len(history["revisions"]), 1)
        self.assertEqual(history["plans"][0]["status"], "applied")
        restored = web_app.restore_revision(session_id, applied["revision_id"], user=self.user)
        self.assertEqual(restored["revision"]["id"], applied["revision_id"])

    def test_cannot_read_another_sessions_revision(self):
        first = web_app.create_session(user=self.user)["session_id"]
        second = web_app.create_session(user=self.user)["session_id"]
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.download_revision(first, "a" * 32, user=self.user)
        self.assertEqual(error.exception.status_code, 404)
        self.assertNotEqual(first, second)

    def test_rename_and_delete_session_api_operations(self):
        session_id = web_app.create_session(user=self.user)["session_id"]
        renamed = web_app.rename_chat(
            session_id,
            web_app.RenameSessionRequest(title="Quarterly approval flow"),
            user=self.user,
        )
        self.assertEqual(renamed["session"]["title"], "Quarterly approval flow")
        deleted = web_app.delete_chat(session_id, user=self.user)
        self.assertTrue(deleted["ok"])
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.read_session(session_id, user=self.user)
        self.assertEqual(error.exception.status_code, 404)

    @patch("web.app.OllamaBPMNClient", FakeOllama)
    def test_plan_based_on_old_version_cannot_overwrite_newer_revision(self):
        session_id = web_app.create_session(user=self.user)["session_id"]
        first = web_app.plan_change(session_id, web_app.TextRequest(text="Create the first version"), user=self.user)
        stale = web_app.plan_change(session_id, web_app.TextRequest(text="Add a second detail"), user=self.user)
        web_app.apply_plan(session_id, web_app.ApplyRequest(plan_id=first["plan_id"]), user=self.user)

        plans = web_app.read_session(session_id, user=self.user)["plans"]
        stale_record = next(plan for plan in plans if plan["id"] == stale["plan_id"])
        self.assertEqual(stale_record["status"], "stale")
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.apply_plan(session_id, web_app.ApplyRequest(plan_id=stale["plan_id"]), user=self.user)
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
