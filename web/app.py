import base64
import binascii
import hashlib
import os
import re
import secrets
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.config import GENERATED_DIR, MAX_GENERATION_ATTEMPTS, MODEL_NAME, OUTPUT_FILE
from core.executor import CodeExecutor
from core.llm_client import OllamaBPMNClient
from core import storage

app = FastAPI(title="BPMN AI Architect")
app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
AUTH_COOKIE = "bpmn_auth"
AUTH_TTL_SECONDS = 60 * 60 * 24 * 30
AVATAR_MAX_BYTES = 2 * 1024 * 1024


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Текст не может быть пустым")
        return value


class ApplyRequest(BaseModel):
    plan_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def trim_title(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Название не может быть пустым")
        return value


class RegistrationRequest(BaseModel):
    login: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=8, max_length=128)
    nickname: Optional[str] = Field(default=None, max_length=40)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value):
        return value.strip().lower()

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value):
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Никнейм не может быть пустым")
        return value


class LoginRequest(BaseModel):
    login: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value):
        return value.strip().lower()


class ProfileRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Никнейм не может быть пустым")
        return value


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AvatarRequest(BaseModel):
    data_url: str = Field(min_length=1, max_length=2_800_000)


def _token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _public_user(user):
    if not user:
        return None
    return {
        "id": user["id"],
        "login": user["login"],
        "nickname": user["nickname"],
        "has_avatar": bool(user.get("avatar_data")),
    }


def _set_auth_cookie(response, token, request):
    response.set_cookie(
        AUTH_COOKIE,
        token,
        max_age=AUTH_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def require_user(request: Request):
    token = request.cookies.get(AUTH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход в аккаунт")
    user = storage.get_user_for_auth_token(_token_hash(token))
    if not user:
        raise HTTPException(status_code=401, detail="Сессия входа истекла. Войдите снова")
    return user


@app.on_event("startup")
def startup():
    storage.init_storage()
    os.makedirs(GENERATED_DIR, exist_ok=True)


def _valid_session(session_id, user_id):
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise HTTPException(status_code=400, detail="Некорректный идентификатор чата")
    session = storage.get_session(session_id)
    if not session or session["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return session


def _history_context(session_id):
    history = storage.get_session_history(session_id)
    recent = history["messages"][-24:]
    return "\n".join(
        f"{message['role']}: {message['content'][:1200]}"
        for message in recent
    )[-12_000:]


@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = Path(__file__).with_name("index.html")
    return index_path.read_text(encoding="utf-8")


@app.post("/auth/register", status_code=201)
def register(request: RegistrationRequest, response: Response, http_request: Request):
    login = request.login.strip().lower()
    try:
        user = storage.create_user(login, request.password, request.nickname or login)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Этот логин уже занят") from exc
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=AUTH_TTL_SECONDS)
    storage.create_auth_session(user["id"], _token_hash(token), expires.isoformat(timespec="seconds"))
    _set_auth_cookie(response, token, http_request)
    return {"user": _public_user(user)}


@app.post("/auth/login")
def login(request: LoginRequest, response: Response, http_request: Request):
    user = storage.verify_user_password(request.login.strip().lower(), request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=AUTH_TTL_SECONDS)
    storage.create_auth_session(user["id"], _token_hash(token), expires.isoformat(timespec="seconds"))
    _set_auth_cookie(response, token, http_request)
    return {"user": _public_user(user)}


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(AUTH_COOKIE)
    if token:
        storage.delete_auth_session(_token_hash(token))
    response.delete_cookie(AUTH_COOKIE, path="/", httponly=True, samesite="lax")
    return {"ok": True}


@app.get("/auth/me")
def current_profile(user=Depends(require_user)):
    return {"user": _public_user(user)}


@app.patch("/auth/profile")
def update_profile(request: ProfileRequest, user=Depends(require_user)):
    updated = storage.update_user_profile(user["id"], request.nickname)
    return {"user": _public_user(updated)}


@app.put("/auth/avatar")
def upload_avatar(request: AvatarRequest, user=Depends(require_user)):
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})", request.data_url)
    if not match:
        raise HTTPException(status_code=400, detail="Загрузите изображение PNG, JPEG или WebP")
    mime_type, encoded = match.groups()
    try:
        image_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Файл изображения повреждён") from exc
    if not image_data or len(image_data) > AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Изображение должно быть меньше 2 МБ")
    signatures = {
        "image/png": image_data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": image_data.startswith(b"\xff\xd8\xff"),
        "image/webp": len(image_data) >= 12 and image_data[:4] == b"RIFF" and image_data[8:12] == b"WEBP",
    }
    if not signatures[mime_type]:
        raise HTTPException(status_code=400, detail="Тип изображения не совпадает с содержимым файла")
    updated = storage.update_user_avatar(user["id"], mime_type, image_data)
    return {"user": _public_user(updated)}


@app.delete("/auth/avatar")
def remove_avatar(user=Depends(require_user)):
    storage.delete_user_avatar(user["id"])
    return {"ok": True}


@app.get("/auth/avatar")
def read_avatar(user=Depends(require_user)):
    if not user.get("avatar_data") or not user.get("avatar_mime"):
        raise HTTPException(status_code=404, detail="Фото профиля не задано")
    return Response(
        content=user["avatar_data"],
        media_type=user["avatar_mime"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.patch("/auth/password")
def update_password(request: PasswordChangeRequest, http_request: Request, user=Depends(require_user)):
    token = http_request.cookies.get(AUTH_COOKIE, "")
    changed = storage.change_user_password(
        user["id"], request.old_password, request.new_password, _token_hash(token) if token else None
    )
    if not changed:
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    return {"ok": True}


@app.get("/sessions")
def list_sessions(user=Depends(require_user)):
    storage.init_storage()
    return {"sessions": storage.list_sessions(user["id"])}


@app.post("/sessions")
def create_session(user=Depends(require_user)):
    storage.init_storage()
    session_id = uuid.uuid4().hex
    storage.create_session(session_id, user_id=user["id"])
    return {"session_id": session_id, **storage.get_session(session_id)}


@app.patch("/sessions/{session_id}")
def rename_chat(session_id: str, request: RenameSessionRequest, user=Depends(require_user)):
    _valid_session(session_id, user["id"])
    storage.rename_session(session_id, request.title)
    return {"session": storage.get_session(session_id)}


@app.delete("/sessions/{session_id}")
def delete_chat(session_id: str, user=Depends(require_user)):
    _valid_session(session_id, user["id"])
    storage.delete_session(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/sessions/{session_id}")
def read_session(session_id: str, user=Depends(require_user)):
    session = _valid_session(session_id, user["id"])
    history = storage.get_session_history(session_id)
    current = storage.get_current_revision(session_id)
    return {"session": session, **history, "current_revision": current}


@app.post("/sessions/{session_id}/plan")
def plan_change(session_id: str, request: TextRequest, user=Depends(require_user)):
    session = _valid_session(session_id, user["id"])
    storage.add_message(session_id, "user", request.text)
    current = storage.get_current_revision(session_id)
    client = OllamaBPMNClient(model_name=MODEL_NAME)
    plan_text = client.generate_plan(
        request.text,
        current_code=current["generated_code"] if current else "",
        history=_history_context(session_id),
    )
    if not plan_text:
        storage.add_message(session_id, "assistant", "Не удалось получить план от Ollama.")
        raise HTTPException(status_code=503, detail="Не удалось получить план от Ollama")

    plan_id = uuid.uuid4().hex
    status = storage.add_plan(
        session_id,
        plan_id,
        request.text,
        plan_text,
        session["current_revision_id"],
    )
    return {"plan_id": plan_id, "plan": plan_text, "status": status, "session_id": session_id}


@app.post("/sessions/{session_id}/apply")
def apply_plan(session_id: str, request: ApplyRequest, user=Depends(require_user)):
    session = _valid_session(session_id, user["id"])
    plan = storage.get_plan(session_id, request.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    if plan["status"] != "pending":
        raise HTTPException(status_code=409, detail="План устарел, уже применён, отклонён или выполняется")
    if plan["parent_revision_id"] != session["current_revision_id"]:
        raise HTTPException(status_code=409, detail="После создания плана диаграмма изменилась. Подготовьте новый план")
    if not storage.claim_plan(session_id, plan["id"], session["current_revision_id"]):
        raise HTTPException(status_code=409, detail="План уже применяется или больше не актуален")

    current = storage.get_current_revision(session_id)
    history_context = _history_context(session_id)
    revision_id = uuid.uuid4().hex
    output_path = os.path.join(GENERATED_DIR, f"{revision_id}.bpmn")
    executor = CodeExecutor(output_filename=output_path)
    client = OllamaBPMNClient(model_name=MODEL_NAME)
    current_code = current["generated_code"] if current else None
    generated_code = None
    last_error = None

    try:
        for _attempt in range(MAX_GENERATION_ATTEMPTS):
            raw_response = client.generate_code(
                plan["request_text"],
                previous_error=last_error,
                previous_code=generated_code,
                current_code=current_code,
                approved_plan=plan["plan_text"],
                history=history_context,
            )
            if not raw_response:
                last_error = "Ollama returned no code"
                continue
            generated_code = client.clean_code(raw_response)
            result = executor.execute(generated_code)
            if result["success"]:
                try:
                    xml_content = Path(output_path).read_text(encoding="utf-8")
                except OSError as exc:
                    last_error = f"Could not read generated BPMN: {exc}"
                    continue
                storage.save_revision(
                    session_id,
                    revision_id,
                    session["current_revision_id"],
                    plan["request_text"],
                    plan["id"],
                    plan["plan_text"],
                    generated_code,
                    xml_content,
                )
                try:
                    os.remove(output_path)
                except OSError:
                    pass
                return {
                    "revision_id": revision_id,
                    "xml": xml_content,
                    "code": generated_code,
                    "session": storage.get_session(session_id),
                }
            last_error = result["error"]
    except storage.StaleRevisionError as exc:
        storage.release_plan_claim(session_id, plan["id"])
        if os.path.exists(output_path):
            os.remove(output_path)
        storage.add_message(session_id, "assistant", "План устарел: текущая версия диаграммы изменилась во время применения.", plan["id"])
        raise HTTPException(status_code=409, detail="Во время применения плана диаграмма изменилась") from exc
    except Exception as exc:
        storage.release_plan_claim(session_id, plan["id"])
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail="Не удалось применить план") from exc

    if os.path.exists(output_path):
        os.remove(output_path)
    storage.release_plan_claim(session_id, plan["id"])
    storage.add_message(session_id, "assistant", f"Не удалось применить план: {last_error}", plan["id"])
    raise HTTPException(status_code=422, detail=f"Не удалось создать корректную BPMN-диаграмму: {last_error}")


@app.post("/sessions/{session_id}/restore/{revision_id}")
def restore_revision(session_id: str, revision_id: str, user=Depends(require_user)):
    _valid_session(session_id, user["id"])
    revision = storage.get_revision(session_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Версия не найдена в этом чате")
    storage.restore_revision(session_id, revision_id)
    return {"revision": revision, "session": storage.get_session(session_id)}


@app.post("/sessions/{session_id}/plans/{plan_id}/discard")
def discard_change_plan(session_id: str, plan_id: str, user=Depends(require_user)):
    _valid_session(session_id, user["id"])
    storage.discard_plan(session_id, plan_id)
    return {"ok": True}


@app.get("/sessions/{session_id}/revisions/{revision_id}/download")
def download_revision(session_id: str, revision_id: str, user=Depends(require_user)):
    _valid_session(session_id, user["id"])
    revision = storage.get_revision(session_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Версия не найдена в этом чате")
    return Response(
        content=revision["xml"],
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="diagram.bpmn"'},
    )


@app.get("/download")
def download_latest_file(user=Depends(require_user)):
    if os.path.isfile(OUTPUT_FILE):
        return FileResponse(OUTPUT_FILE, filename="diagram.bpmn", media_type="application/xml")
    raise HTTPException(status_code=404, detail="Файл не найден")
