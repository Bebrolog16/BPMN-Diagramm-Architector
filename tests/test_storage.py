import tempfile
import sqlite3
import unittest
from pathlib import Path

from core import storage


class TestSessionStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = storage.DATABASE_FILE
        storage.DATABASE_FILE = str(Path(self.temp_dir.name) / "history.sqlite3")
        storage.init_storage()
        self.session_id = "a" * 32
        storage.create_session(self.session_id)

    def tearDown(self):
        storage.DATABASE_FILE = self.original_database
        self.temp_dir.cleanup()

    def test_persists_plan_messages_revisions_and_restore_pointer(self):
        first_plan = "b" * 32
        storage.add_message(self.session_id, "user", "Create an order flow")
        storage.add_plan(self.session_id, first_plan, "Create an order flow", "Add order and approval", None)
        storage.save_revision(
            self.session_id, "c" * 32, None, "Create an order flow", first_plan,
            "Add order and approval", "sdk = DiagramSDK()", "<definitions />",
        )
        second_plan = "d" * 32
        storage.add_message(self.session_id, "user", "Add shipping")
        storage.add_plan(self.session_id, second_plan, "Add shipping", "Add a delivery lane", "c" * 32)
        storage.save_revision(
            self.session_id, "e" * 32, "c" * 32, "Add shipping", second_plan,
            "Add a delivery lane", "sdk = DiagramSDK()", "<definitions id='second' />",
        )

        storage.restore_revision(self.session_id, "c" * 32)
        session = storage.get_session(self.session_id)
        history = storage.get_session_history(self.session_id)
        current = storage.get_current_revision(self.session_id)

        self.assertEqual(session["current_revision_id"], "c" * 32)
        self.assertEqual(current["xml"], "<definitions />")
        self.assertEqual(len(history["revisions"]), 2)
        self.assertEqual(len(history["messages"]), 7)
        self.assertEqual(storage.get_plan(self.session_id, second_plan)["status"], "applied")

    def test_session_queries_do_not_cross_session_boundaries(self):
        other_session = "f" * 32
        storage.create_session(other_session)
        storage.add_message(self.session_id, "user", "A")
        storage.add_plan(self.session_id, "1" * 32, "A", "Plan A", None)
        storage.add_message(other_session, "user", "B")
        storage.add_plan(other_session, "2" * 32, "B", "Plan B", None)

        self.assertEqual(len(storage.get_session_history(self.session_id)["messages"]), 2)
        self.assertEqual(len(storage.get_session_history(other_session)["messages"]), 2)
        self.assertNotEqual(
            storage.get_session_history(self.session_id)["messages"][0]["content"],
            storage.get_session_history(other_session)["messages"][0]["content"],
        )

    def test_new_revision_marks_other_pending_plans_stale(self):
        storage.add_plan(self.session_id, "3" * 32, "Change A", "Plan A", None)
        storage.add_plan(self.session_id, "4" * 32, "Change B", "Plan B", None)
        storage.save_revision(
            self.session_id, "5" * 32, None, "Change A", "3" * 32,
            "Plan A", "sdk = DiagramSDK()", "<definitions />",
        )
        plans = storage.get_session_history(self.session_id)["plans"]
        statuses = {plan["id"]: plan["status"] for plan in plans}
        self.assertEqual(statuses["3" * 32], "applied")
        self.assertEqual(statuses["4" * 32], "stale")

    def test_revision_commit_cannot_overwrite_a_concurrent_restore(self):
        storage.save_revision(
            self.session_id, "6" * 32, None, "First", "7" * 32,
            "First plan", "code v1", "<definitions id='one' />",
        )
        storage.add_plan(self.session_id, "8" * 32, "Second", "Second plan", "6" * 32)
        storage.save_revision(
            self.session_id, "9" * 32, "6" * 32, "Second", "8" * 32,
            "Second plan", "code v2", "<definitions id='two' />",
        )
        storage.add_plan(self.session_id, "a" * 32, "Third", "Third plan", "9" * 32)
        self.assertTrue(storage.claim_plan(self.session_id, "a" * 32, "9" * 32))
        storage.restore_revision(self.session_id, "6" * 32)

        with self.assertRaises(storage.StaleRevisionError):
            storage.save_revision(
                self.session_id, "b" * 32, "9" * 32, "Third", "a" * 32,
                "Third plan", "code v3", "<definitions id='three' />",
            )
        self.assertEqual(storage.get_session(self.session_id)["current_revision_id"], "6" * 32)
        self.assertIsNone(storage.get_revision(self.session_id, "b" * 32))

    def test_migrates_old_plan_status_constraint_and_keeps_existing_rows(self):
        legacy_path = str(Path(self.temp_dir.name) / "legacy.sqlite3")
        connection = sqlite3.connect(legacy_path)
        connection.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, current_revision_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE plans (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                parent_revision_id TEXT, request_text TEXT NOT NULL, plan_text TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'applied', 'discarded')),
                created_at TEXT NOT NULL
            );
            INSERT INTO sessions VALUES ('legacy-session', 'Legacy', NULL, 'now', 'now');
            INSERT INTO plans VALUES ('legacy-plan', 'legacy-session', NULL, 'request', 'plan', 'pending', 'now');
            """
        )
        connection.close()

        original_database = storage.DATABASE_FILE
        storage.DATABASE_FILE = legacy_path
        try:
            storage.init_storage()
            self.assertEqual(storage.get_plan("legacy-session", "legacy-plan")["status"], "pending")
            self.assertTrue(storage.claim_plan("legacy-session", "legacy-plan", None))
            self.assertEqual(storage.get_plan("legacy-session", "legacy-plan")["status"], "applying")
        finally:
            storage.DATABASE_FILE = original_database


if __name__ == "__main__":
    unittest.main()
