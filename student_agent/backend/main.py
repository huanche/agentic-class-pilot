"""Student classroom API with lesson-scoped LangGraph discussion."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.infrastructure import persistence
from backend.infrastructure import published_knowledge
from backend.session import service as learning_session
from backend.session import command_runtime
from backend.contracts import SessionError
from backend.internal_platform import router as internal_platform_router

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "out"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    published_knowledge.start_worker()
    command_runtime.start_worker()
    try:
        yield
    finally:
        published_knowledge.stop_worker()
        command_runtime.stop_worker()


app = FastAPI(title="Student Agent", lifespan=lifespan)
app.include_router(internal_platform_router)


@app.exception_handler(SessionError)
async def session_error(_request: Request, error: SessionError):
    content = {"detail": error.detail}
    if error.code:
        content["code"] = error.code
    return JSONResponse(status_code=error.status_code, content=content)


class StartRequest(BaseModel):
    launch_token: str = ""


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class BrowserRestoreRequest(BaseModel):
    snapshot: str = Field(min_length=1, max_length=4_000_000)
    launch_token: str = ""


class ResetLessonRequest(BaseModel):
    launch_token: str = ""


class ResumeRequest(StartRequest):
    lesson_id: str = Field(min_length=1, max_length=200)


class CommandRequest(StartRequest):
    commandId: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    expectedStateVersion: int = Field(ge=0, strict=True)
    contentGeneration: int = Field(ge=0, strict=True)
    type: str = Field(min_length=1, max_length=40)
    payload: dict = Field(default_factory=dict)


@app.post("/api/session/start")
def start(body: StartRequest) -> dict:
    return learning_session.start(body.launch_token)


@app.post("/api/session/resume")
def resume(body: ResumeRequest, background_tasks: BackgroundTasks) -> dict:
    return learning_session.resume(body.launch_token, body.lesson_id, background_tasks)


@app.post("/api/session/browser-restore")
def browser_restore(body: BrowserRestoreRequest, background_tasks: BackgroundTasks) -> dict:
    return learning_session.browser_restore(body.snapshot, body.launch_token, background_tasks)


@app.get("/api/session/health")
def health() -> dict:
    if not (os.environ.get("PLATFORM_AUTH_URL") and os.environ.get("STUDENT_SERVICE_KEY")):
        raise HTTPException(503, "平台连接尚未配置")
    if not (os.environ.get("STUDENT_AGENT_API_KEY") or os.environ.get("LLM_API_KEY")):
        raise HTTPException(503, "课堂导师模型尚未配置")
    if not (os.environ.get("STUDENT_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        raise HTTPException(503, "学习数据库尚未配置")
    return {"ok": True}


@app.get("/api/session/ready")
def ready() -> dict:
    from backend.infrastructure.release_check import check, ReleaseCheckError
    try:
        return check()
    except ReleaseCheckError as error:
        raise HTTPException(503, str(error)) from None


@app.get("/api/session/platform-entry")
def platform_entry() -> dict:
    return {
        "platformUrl": os.environ.get("FRONTEND_HOST", "http://localhost:8088").rstrip("/"),
        "demoEnabled": bool(os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL")),
        "freshSessionMode": persistence.fresh_session_mode(),
    }


@app.get("/demo-player")
def demo_player():
    if not os.environ.get("STUDENT_NEW_DEMO_PLAYER_URL"):
        raise HTTPException(404)
    return HTMLResponse("""<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<body style='margin:0;display:grid;place-items:center;height:100vh;background:#18243b;color:white;font:20px sans-serif'>
<button style='padding:16px 24px;font:inherit' onclick="parent.postMessage({type:'PLAYBACK_ENDED'},location.origin)">模拟视频播放完成</button>
</body></html>""")


@app.get("/api/session/{sid}")
def read(sid: str, background_tasks: BackgroundTasks) -> dict:
    return learning_session.read(sid, background_tasks)


@app.post("/api/session/{sid}/begin/{lesson_id}")
def begin(sid: str, lesson_id: str, background_tasks: BackgroundTasks) -> dict:
    return learning_session.begin(sid, lesson_id, background_tasks)


@app.post("/api/session/{sid}/commands")
def execute_command(sid: str, body: CommandRequest):
    result = command_runtime.execute(sid, body.model_dump(exclude={"launch_token"}), body.launch_token)
    status = 503 if result["status"] == "failed" else 202 if result["status"] in {"pending", "processing"} else 200
    return JSONResponse(status_code=status, content=result)


@app.post("/api/session/{sid}/commands/{command_id}/status")
def command_status(sid: str, command_id: str, body: StartRequest):
    return command_runtime.status(sid, command_id, body.launch_token)


@app.post("/api/session/{sid}/learning-records")
def learning_records(sid: str, body: StartRequest):
    return command_runtime.read_records(sid, body.launch_token)


@app.post("/api/session/{sid}/playback")
def replay_playback(sid: str, body: StartRequest) -> dict:
    """Resolve playback without changing the saved feedback or learning phase."""
    return learning_session.replay_playback(sid, body.launch_token)


@app.post("/api/session/{sid}/prepare")
def retry_preparation(sid: str, background_tasks: BackgroundTasks) -> dict:
    return learning_session.retry_preparation(sid, background_tasks)


@app.post("/api/session/{sid}/discussion")
def discussion(sid: str, background_tasks: BackgroundTasks) -> dict:
    return learning_session.discussion(sid, background_tasks)


@app.post("/api/session/{sid}/message")
def message(sid: str, body: MessageRequest) -> dict:
    return learning_session.message(sid, body.text)


@app.post("/api/session/{sid}/end")
def end(sid: str, background_tasks: BackgroundTasks) -> dict:
    return learning_session.end(sid, background_tasks)


@app.post("/api/session/{sid}/reset")
def reset_lesson(sid: str, body: ResetLessonRequest, background_tasks: BackgroundTasks) -> dict:
    return learning_session.reset_lesson(sid, body.launch_token, background_tasks)


@app.get("/api/session/{sid}/feedback")
def feedback(sid: str) -> dict:
    return learning_session.feedback(sid)


@app.post("/api/session/{sid}/postclass/start")
def start_postclass(sid: str) -> dict:
    return learning_session.start_postclass(sid)


@app.post("/api/session/{sid}/postclass/message")
def postclass_message(sid: str, body: MessageRequest) -> dict:
    return learning_session.postclass_message(sid, body.text)


if OUT.is_dir():
    app.mount("/app", StaticFiles(directory=OUT, html=True), name="student-frontend")


@app.get("/")
def index():
    if not OUT.is_dir():
        raise HTTPException(503, "请先构建前端：npm run build")
    return FileResponse(OUT / "index.html")
