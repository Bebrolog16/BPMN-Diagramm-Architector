"""Local SQLite persistence for sessions, plans, messages, and diagram revisions."""

import os
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from core.config import DATABASE_FILE


class StaleRevisionError(Exception):
    """Raised when a plan's base revision changed before commit."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_storage():
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nickname TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                avatar_mime TEXT,
                avatar_data BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
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
            CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id);
            """
        )
        session_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        if "user_id" not in session_columns:
            connection.execute(
                "ALTER TABLE sessions ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE"
            )
        _migrate_plan_status_check(connection)


PASSWORD_ITERATIONS = 310_000


def _hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _password_matches(password, encoded):
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (AttributeError, TypeError, ValueError):
        return False


def create_user(login, password, nickname):
    now = _now()
    user_id = secrets.token_hex(16)
    password_hash = _hash_password(password)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        is_first_user = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None
        connection.execute(
            "INSERT INTO users(id, login, nickname, password_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, login, nickname, password_hash, now, now),
        )
        if is_first_user:
            # Existing single-user chat history belongs to the initial local account.
            connection.execute("UPDATE sessions SET user_id = ? WHERE user_id IS NULL", (user_id,))
    return get_user(user_id)


def get_user(user_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, login, nickname, avatar_mime, avatar_data, created_at, updated_at "
            "FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_login(login):
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE login = ? COLLATE NOCASE", (login,)).fetchone()
    return dict(row) if row else None


def verify_user_password(login, password):
    user = get_user_by_login(login)
    if not user:
        # Keep the unknown-login path close to the normal password-check cost.
        _password_matches(password, "pbkdf2_sha256$310000$" + ("00" * 16) + "$" + ("00" * 32))
        return None
    return user if _password_matches(password, user["password_hash"]) else None


def create_auth_session(user_id, token_hash, expires_at):
    now = _now()
    with _connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            "INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, expires_at),
        )


def get_user_for_auth_token(token_hash):
    now = _now()
    with _connect() as connection:
        row = connection.execute(
            "SELECT u.id, u.login, u.nickname, u.avatar_mime, u.avatar_data, u.created_at, u.updated_at "
            "FROM auth_sessions a JOIN users u ON u.id = a.user_id "
            "WHERE a.token_hash = ? AND a.expires_at > ?",
            (token_hash, now),
        ).fetchone()
    return dict(row) if row else None


def delete_auth_session(token_hash):
    with _connect() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))


def update_user_profile(user_id, nickname):
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET nickname = ?, updated_at = ? WHERE id = ?",
            (nickname, _now(), user_id),
        )
    return get_user(user_id)


def update_user_avatar(user_id, mime_type, image_data):
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET avatar_mime = ?, avatar_data = ?, updated_at = ? WHERE id = ?",
            (mime_type, image_data, _now(), user_id),
        )
    return get_user(user_id)


def delete_user_avatar(user_id):
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET avatar_mime = NULL, avatar_data = NULL, updated_at = ? WHERE id = ?",
            (_now(), user_id),
        )


def change_user_password(user_id, old_password, new_password, current_token_hash=None):
    with _connect() as connection:
        user = connection.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or not _password_matches(old_password, user["password_hash"]):
            return False
        connection.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (_hash_password(new_password), _now(), user_id),
        )
        if current_token_hash:
            connection.execute(
                "DELETE FROM auth_sessions WHERE user_id = ? AND token_hash != ?",
                (user_id, current_token_hash),
            )
        else:
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
    return True


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


def create_session(session_id, title="Новая диаграмма", user_id=None):
    now = _now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO sessions(id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, title, now, now),
        )


def list_sessions(user_id=None):
    with _connect() as connection:
        query = (
            "SELECT id, title, current_revision_id, created_at, updated_at "
            "FROM sessions"
        )
        params = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            params = (user_id,)
        rows = connection.execute(query + " ORDER BY updated_at DESC", params).fetchall()
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
