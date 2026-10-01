"""Local SQLite persistence for sessions, plans, messages, and diagram revisions."""

import os
import sqlite3
from datetime import datetime, timezone

from core.config import DATABASE_FILE


class StaleRevisionError(Exception):
    """Raised when a plan's base revision changed before commit."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def init_storage():
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                current_revision_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revisions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                parent_revision_id TEXT,
                request_text TEXT NOT NULL,
                plan_text TEXT NOT NULL,
                generated_code TEXT NOT NULL,
                xml TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                parent_revision_id TEXT,
                request_text TEXT NOT NULL,
                plan_text TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'applying', 'applied', 'discarded', 'stale')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                revision_id TEXT,
                plan_id TEXT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_session_order
                ON messages(session_id, id);
            CREATE INDEX IF NOT EXISTS revisions_session_order
                ON revisions(session_id, created_at);
            CREATE INDEX IF NOT EXISTS plans_session_order
                ON plans(session_id, created_at);
            """
        )
        _migrate_plan_status_check(connection)


def _migrate_plan_status_check(connection):
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'plans'"
    ).fetchone()
    definition = (row["sql"] or "").lower() if row else ""
    if "'applying'" in definition and "'stale'" in definition:
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("DROP INDEX IF EXISTS plans_session_order")
        connection.execute("ALTER TABLE plans RENAME TO plans_before_status_migration")
        connection.execute(
            """CREATE TABLE plans (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                parent_revision_id TEXT,
                request_text TEXT NOT NULL,
                plan_text TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'applying', 'applied', 'discarded', 'stale')),
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO plans(id, session_id, parent_revision_id, request_text, plan_text, status, created_at) "
            "SELECT id, session_id, parent_revision_id, request_text, plan_text, status, created_at "
            "FROM plans_before_status_migration"
        )
        connection.execute("DROP TABLE plans_before_status_migration")
        connection.execute(
            "CREATE INDEX plans_session_order ON plans(session_id, created_at)"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def create_session(session_id, title="Новая диаграмма"):
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )


def list_sessions():
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, title, current_revision_id, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def rename_session(session_id, title):
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), session_id),
        )
    return cursor.rowcount == 1


def delete_session(session_id):
    with _connect() as connection:
        cursor = connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cursor.rowcount == 1


def get_session(session_id):
    with _connect() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_current_revision(session_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT r.* FROM revisions r JOIN sessions s ON s.current_revision_id = r.id "
            "WHERE s.id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def get_revision(session_id, revision_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM revisions WHERE session_id = ? AND id = ?",
            (session_id, revision_id),
        ).fetchone()
    return dict(row) if row else None


def get_session_history(session_id):
    with _connect() as connection:
        messages = connection.execute(
            "SELECT id, revision_id, plan_id, role, content, created_at "
            "FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        revisions = connection.execute(
            "SELECT id, parent_revision_id, request_text, plan_text, created_at "
            "FROM revisions WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        plans = connection.execute(
            "SELECT id, parent_revision_id, request_text, plan_text, status, created_at "
            "FROM plans WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    return {
        "messages": [dict(row) for row in messages],
        "revisions": [dict(row) for row in revisions],
        "plans": [dict(row) for row in plans],
    }


def add_plan(session_id, plan_id, request_text, plan_text, parent_revision_id):
    now = _now()
    with _connect() as connection:
        session = connection.execute(
            "SELECT current_revision_id FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        status = "pending" if session and session["current_revision_id"] == parent_revision_id else "stale"
        connection.execute(
            "INSERT INTO plans(id, session_id, parent_revision_id, request_text, plan_text, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_id, session_id, parent_revision_id, request_text, plan_text, status, now),
        )
        connection.execute(
            "INSERT INTO messages(session_id, plan_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (session_id, plan_id, plan_text, now),
        )
        connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    return status


def get_plan(session_id, plan_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM plans WHERE session_id = ? AND id = ?",
            (session_id, plan_id),
        ).fetchone()
    return dict(row) if row else None


def claim_plan(session_id, plan_id, parent_revision_id):
    """Atomically allow only one request to apply a still-current plan."""
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE plans SET status = 'applying' WHERE session_id = ? AND id = ? "
            "AND status = 'pending' AND parent_revision_id IS ? "
            "AND EXISTS (SELECT 1 FROM sessions WHERE id = ? AND current_revision_id IS ?)",
            (session_id, plan_id, parent_revision_id, session_id, parent_revision_id),
        )
    return cursor.rowcount == 1


def release_plan_claim(session_id, plan_id):
    with _connect() as connection:
        connection.execute(
            "UPDATE plans SET status = 'pending' WHERE session_id = ? AND id = ? AND status = 'applying'",
            (session_id, plan_id),
        )


def save_revision(session_id, revision_id, parent_revision_id, request_text, plan_id,
                  plan_text, generated_code, xml):
    now = _now()
    with _connect() as connection:
        cursor = connection.execute(
            "UPDATE sessions SET current_revision_id = ?, title = CASE WHEN current_revision_id IS NULL "
            "THEN ? ELSE title END, updated_at = ? WHERE id = ? AND current_revision_id IS ?",
            (revision_id, request_text[:80], now, session_id, parent_revision_id),
        )
        if cursor.rowcount != 1:
            raise StaleRevisionError("The current diagram revision changed before commit")
        connection.execute(
            "INSERT INTO revisions(id, session_id, parent_revision_id, request_text, plan_text, "
            "generated_code, xml, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (revision_id, session_id, parent_revision_id, request_text, plan_text, generated_code, xml, now),
        )
        connection.execute(
            "UPDATE plans SET status = 'stale' WHERE session_id = ? AND status = 'pending' "
            "AND parent_revision_id IS ?",
            (session_id, parent_revision_id),
        )
        connection.execute("UPDATE plans SET status = 'applied' WHERE id = ?", (plan_id,))
        connection.execute(
            "INSERT INTO messages(session_id, revision_id, plan_id, role, content, created_at) "
            "VALUES (?, ?, ?, 'assistant', ?, ?)",
            (session_id, revision_id, plan_id, f"Изменения сохранены как версия {revision_id[:8]}.", now),
        )


def restore_revision(session_id, revision_id):
    now = _now()
    with _connect() as connection:
        connection.execute(
            "UPDATE sessions SET current_revision_id = ?, updated_at = ? WHERE id = ?",
            (revision_id, now, session_id),
        )
        connection.execute(
            "UPDATE plans SET status = 'stale' WHERE session_id = ? AND status IN ('pending', 'applying') "
            "AND parent_revision_id IS NOT ?",
            (session_id, revision_id),
        )
        connection.execute(
            "INSERT INTO messages(session_id, revision_id, role, content, created_at) "
            "VALUES (?, ?, 'system', ?, ?)",
            (session_id, revision_id, f"Текущей выбрана версия {revision_id[:8]}.", now),
        )


def add_message(session_id, role, content, plan_id=None):
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages(session_id, plan_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, plan_id, role, content, now),
        )
        connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))


def discard_plan(session_id, plan_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT status FROM plans WHERE session_id = ? AND id = ?",
            (session_id, plan_id),
        ).fetchone()
        connection.execute(
            "UPDATE plans SET status = 'discarded' WHERE session_id = ? AND id = ? AND status = 'pending'",
            (session_id, plan_id),
        )
        if row and row["status"] == "pending":
            now = _now()
            connection.execute(
                "INSERT INTO messages(session_id, plan_id, role, content, created_at) "
                "VALUES (?, ?, 'system', 'План отклонён пользователем.', ?)",
                (session_id, plan_id, now),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
