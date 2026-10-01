import os
import re
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.config import GENERATED_DIR, MAX_GENERATION_ATTEMPTS, MODEL_NAME, OUTPUT_FILE
from core.executor import CodeExecutor
from core.llm_client import OllamaBPMNClient
from core import storage

app = FastAPI(title="BPMN AI Architect")


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)

    @field_validator("text")
    @classmethod
    def trim_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Text cannot be blank")
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
            raise ValueError("Title cannot be blank")
        return value


@app.on_event("startup")
def startup():
    storage.init_storage()
    os.makedirs(GENERATED_DIR, exist_ok=True)


def _valid_session(session_id):
    if not re.fullmatch(r"[0-9a-f]{32}", session_id):
        raise HTTPException(status_code=400, detail="Invalid session id")
    session = storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
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


@app.get("/sessions")
def list_sessions():
    storage.init_storage()
    return {"sessions": storage.list_sessions()}


@app.post("/sessions")
def create_session():
    storage.init_storage()
    session_id = uuid.uuid4().hex
    storage.create_session(session_id)
    return {"session_id": session_id, **storage.get_session(session_id)}


@app.patch("/sessions/{session_id}")
def rename_chat(session_id: str, request: RenameSessionRequest):
    _valid_session(session_id)
    storage.rename_session(session_id, request.title)
    return {"session": storage.get_session(session_id)}


@app.delete("/sessions/{session_id}")
def delete_chat(session_id: str):
    _valid_session(session_id)
    storage.delete_session(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/sessions/{session_id}")
def read_session(session_id: str):
    session = _valid_session(session_id)
    history = storage.get_session_history(session_id)
    current = storage.get_current_revision(session_id)
    return {"session": session, **history, "current_revision": current}


@app.post("/sessions/{session_id}/plan")
def plan_change(session_id: str, request: TextRequest):
    session = _valid_session(session_id)
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
        raise HTTPException(status_code=503, detail="Could not get a plan from Ollama")

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
def apply_plan(session_id: str, request: ApplyRequest):
    session = _valid_session(session_id)
    plan = storage.get_plan(session_id, request.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan["status"] != "pending":
        raise HTTPException(status_code=409, detail="This plan is stale, already applied, discarded, or in progress")
    if plan["parent_revision_id"] != session["current_revision_id"]:
        raise HTTPException(status_code=409, detail="The diagram changed after this plan; create a fresh plan")
    if not storage.claim_plan(session_id, plan["id"], session["current_revision_id"]):
        raise HTTPException(status_code=409, detail="This plan is already being applied or is no longer current")

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
        raise HTTPException(status_code=409, detail="The diagram changed while this plan was being applied") from exc
    except Exception as exc:
        storage.release_plan_claim(session_id, plan["id"])
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail="Could not apply plan") from exc

    if os.path.exists(output_path):
        os.remove(output_path)
    storage.release_plan_claim(session_id, plan["id"])
    storage.add_message(session_id, "assistant", f"Не удалось применить план: {last_error}", plan["id"])
    raise HTTPException(status_code=422, detail=f"Could not generate valid BPMN: {last_error}")


@app.post("/sessions/{session_id}/restore/{revision_id}")
def restore_revision(session_id: str, revision_id: str):
    _valid_session(session_id)
    revision = storage.get_revision(session_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found in this session")
    storage.restore_revision(session_id, revision_id)
    return {"revision": revision, "session": storage.get_session(session_id)}


@app.post("/sessions/{session_id}/plans/{plan_id}/discard")
def discard_change_plan(session_id: str, plan_id: str):
    _valid_session(session_id)
    storage.discard_plan(session_id, plan_id)
    return {"ok": True}


@app.get("/sessions/{session_id}/revisions/{revision_id}/download")
def download_revision(session_id: str, revision_id: str):
    _valid_session(session_id)
    revision = storage.get_revision(session_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found in this session")
    return Response(
        content=revision["xml"],
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="diagram.bpmn"'},
    )


@app.get("/download")
def download_latest_file():
    if os.path.isfile(OUTPUT_FILE):
        return FileResponse(OUTPUT_FILE, filename="diagram.bpmn", media_type="application/xml")
    raise HTTPException(status_code=404, detail="File not found")
