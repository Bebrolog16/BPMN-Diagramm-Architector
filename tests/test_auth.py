import tempfile
import unittest
from pathlib import Path

from fastapi import Request, Response

from core import storage
from web import app as web_app


class TestAuthentication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = storage.DATABASE_FILE
        self.original_generated_dir = web_app.GENERATED_DIR
        storage.DATABASE_FILE = str(Path(self.temp_dir.name) / "accounts.sqlite3")
        web_app.GENERATED_DIR = str(Path(self.temp_dir.name) / "generated")
        storage.init_storage()

    def tearDown(self):
        storage.DATABASE_FILE = self.original_database
        web_app.GENERATED_DIR = self.original_generated_dir
        self.temp_dir.cleanup()

    def request(self, cookie=None):
        headers = [(b"cookie", cookie.encode("ascii"))] if cookie else []
        return Request({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/", "raw_path": b"/",
            "query_string": b"", "root_path": "", "headers": headers,
            "server": ("testserver", 80), "client": ("testclient", 12345),
            "app": web_app.app,
        })

    def register(self, login="sergey"):
        response = Response()
        result = web_app.register(
            web_app.RegistrationRequest(login=login, password="long-password-123", nickname="Сергей"),
            response,
            self.request(),
        )
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        return result["user"], cookie

    def test_register_claims_existing_local_history_and_accounts_are_isolated(self):
        legacy_id = "a" * 32
        storage.create_session(legacy_id, title="Старая история")

        first, _cookie = self.register()
        first_chats = web_app.list_sessions(first)
        self.assertEqual([chat["id"] for chat in first_chats["sessions"]], [legacy_id])

        own_chat = web_app.create_session(first)["session_id"]
        second, _second_cookie = self.register("another")
        self.assertEqual(web_app.list_sessions(second)["sessions"], [])
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.read_session(own_chat, second)
        self.assertEqual(error.exception.status_code, 404)

    def test_profile_photo_password_and_logout(self):
        user, cookie = self.register()
        updated = web_app.update_profile(web_app.ProfileRequest(nickname="Новый ник"), user)
        user = updated["user"]
        self.assertEqual(user["nickname"], "Новый ник")

        png_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qO8AAAAASUVORK5CYII="
        avatar = web_app.upload_avatar(
            web_app.AvatarRequest(data_url=f"data:image/png;base64,{png_data}"), user
        )
        user = avatar["user"]
        self.assertTrue(user["has_avatar"])
        authenticated_user = storage.get_user(user["id"])
        self.assertEqual(web_app.read_avatar(authenticated_user).media_type, "image/png")
        web_app.remove_avatar(authenticated_user)

        with self.assertRaises(web_app.HTTPException) as error:
            web_app.update_password(
                web_app.PasswordChangeRequest(old_password="incorrect", new_password="new-password-456"),
                self.request(cookie), user,
            )
        self.assertEqual(error.exception.status_code, 400)
        web_app.update_password(
            web_app.PasswordChangeRequest(old_password="long-password-123", new_password="new-password-456"),
            self.request(cookie), user,
        )
        web_app.logout(self.request(cookie), Response())
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.require_user(self.request(cookie))
        self.assertEqual(error.exception.status_code, 401)

        login = web_app.login(
            web_app.LoginRequest(login="sergey", password="new-password-456"), Response(), self.request()
        )
        self.assertEqual(login["user"]["login"], "sergey")

    def test_protected_routes_reject_anonymous_requests_and_duplicate_login(self):
        with self.assertRaises(web_app.HTTPException) as error:
            web_app.require_user(self.request())
        self.assertEqual(error.exception.status_code, 401)
        self.register()
        with self.assertRaises(web_app.HTTPException) as error:
            self.register(login="SERGEY")
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
