"""会话层服务：把编排器接进真实对话。

职责边界（很重要，别越界）：
  - **编排**在 `orchestrator/agent.py`：讲哪一段、问哪一题、什么时候切幕、打几星。
  - **本文件只做四件事**：持有会话状态、跑心跳时钟、收发消息、导出学情。
  在这里写任何教学判断都会让编排结果变得不可预测。

为什么不用 LangGraph 的 checkpointer：
  `langgraph-checkpoint-sqlite` 在本机装不上。而 `load_plan` 是幂等的
  （host_phase 初始化过就返回空），所以把上一轮的完整 state 全量注入就能续上，
  持久化只需要写一个 JSON 文件，进程重启也不丢。

跑起来：
    uvicorn apps.server:app --port 8000      # 然后浏览器打开 http://127.0.0.1:8000/

环境变量：
    AGENT_TICK_SECONDS  心跳间隔，默认 10 秒
    AGENT_PORT          端口，默认 8000
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

from agent import (  # noqa: E402
    EVENT_BEGIN, EVENT_MEDIA_DONE, EVENT_NEXT_STAGE,
    STAGE_NAMES, STAR_STATUS, build_graph, initial_state, kp_title, run_turn_stateless,
)

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    raise SystemExit("缺依赖：pip install fastapi uvicorn")


TICK_SECONDS = float(os.environ.get("AGENT_TICK_SECONDS", "10"))
SESSIONS_DIR = ROOT / "runtime" / "sessions"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 会话状态 → 此刻前端该显示哪些按钮（前端照着这个渲染，不要自己猜能不能按）
ACTIONS = {
    "idle": ["begin"],                                  # 已进教室，等老师点「开始上课」
    "running": ["message", "media_done", "next_stage", "stop"],
    "ended": ["export"],
}

GRAPH = build_graph()          # 不带 checkpointer：状态由本模块持有并回灌

# sid -> {"state": dict, "messages": [...], "lock": Lock, "stop": Event, "thread": Thread}
SESSIONS: dict[str, dict] = {}
_REGISTRY_LOCK = threading.Lock()

app = FastAPI(title="主动引导智能体 · 会话层")


# ═══════════════════════════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════════════════════════

def _now() -> str:
    """会话层负责取时间，图里不许自己读时钟 —— 这样编排逻辑才可单测、可回放。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _path(sid: str) -> Path:
    return SESSIONS_DIR / f"{sid}.json"


def _persist(sid: str, state: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _path(sid).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _restore(sid: str) -> dict | None:
    """进程重启后从磁盘续上。旧文件可能缺新字段，用 initial_state 兜底。"""
    p = _path(sid)
    if not p.is_file():
        return None
    try:
        saved = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    merged = initial_state(sid)
    merged.update(saved)
    return merged


def _get(sid: str) -> dict:
    with _REGISTRY_LOCK:
        s = SESSIONS.get(sid)
        if s is None:
            state = _restore(sid)
            if state is None:
                raise HTTPException(404, f"会话不存在：{sid}")
            s = SESSIONS[sid] = {
                "state": state,
                "messages": [],
                "lock": threading.Lock(),
                "stop": threading.Event(),
                "thread": None,
                "time_scale": float(state.get("time_scale") or 1.0),
            }
            # 进程重启后，还在上的课要把心跳线程接回来，否则课停在原地不动
            if state.get("lesson_status") == "running":
                stop = threading.Event()
                s["stop"] = stop
                t = threading.Thread(target=_heartbeat, args=(sid, stop), daemon=True)
                s["thread"] = t
                t.start()
        return s


def _step(sid: str, message: str = "", speaker: str = "student",
          tick_only: bool = False, external_event: str | None = None,
          status: str | None = None) -> dict:
    """跑一轮编排。加锁：心跳线程、外部事件与学生发言可能同时到，图的状态不能并发写。

    `external_event` 是本轮要告诉编排器的外部事件（见 agent.EVENT_*），
    每轮显式传值，None 表示本轮没事件。返回本轮结束后的 state。
    """
    s = _get(sid)
    with s["lock"]:
        if status:
            s["state"]["lesson_status"] = status
        # LangGraph 只保留 ClassroomState TypedDict 定义的键；平台上下文
        # 挂在会话包装层，每轮回注入 state 供 load_plan/judge_mastery 读取。
        for extra in ("platform", "learning_context"):
            if extra in s and extra not in s["state"]:
                s["state"][extra] = s[extra]
        st = run_turn_stateless(
            GRAPH, s["state"], _now(), message, speaker,
            tick_only=tick_only, time_scale=s["time_scale"],
            external_event=external_event,
        )
        for extra in ("platform", "learning_context"):
            if extra in s and extra not in st:
                st[extra] = s[extra]
        # 下课：advance_stage 置 student_status=ended 那一刻，课就算结束
        if st.get("host_phase") == "ending" and st.get("student_status") == "ended":
            st["lesson_status"] = "ended"
        for extra in ("platform", "learning_context"):
            if extra in s:
                st[extra] = s[extra]
        s["state"] = st
        reply = (st.get("reply_text") or "").strip()
        if reply:
            s["messages"].append({
                "seq": len(s["messages"]),
                "role": "teacher",
                "text": reply,
                "at": st.get("now"),
                "phase": st.get("host_phase"),
                "llm": bool(st.get("llm_used")),
            })
        # 学习数据同步到 student schema（幂等；ctx 从 state 读，重启可恢复；
        # 放在消息 append 之后，保证本轮 AI 回复也被记录；失败不阻塞课堂）
        try:
            ctx = st.get("platform") or {}
            if ctx.get("userId"):
                from apps.integration import persistence
                seen = s.get("_persisted_message_seq", 0)
                messages = s.get("messages") or []
                for index, msg in enumerate(messages[seen:], start=seen + 1):
                    persistence.upsert_message(
                        session_key=sid, user_id=ctx["userId"],
                        course_id=ctx.get("courseId", ""),
                        publication_id=ctx.get("publicationId", ""),
                        seq=index, role=msg.get("role", "student"),
                        phase=msg.get("phase") or st.get("host_phase"),
                        content=msg.get("text", ""))
                s["_persisted_message_seq"] = len(messages)
                updates = st.get("mastery_updates") or []
                for item in updates:
                    persistence.upsert_mastery(
                        session_key=sid, user_id=ctx["userId"],
                        course_id=ctx.get("courseId", ""),
                        publication_id=ctx.get("publicationId", ""),
                        knowledge_point_id=item.get("kp_id", ""),
                        stars=int(item.get("new_stars", 0)),
                        status=item.get("new_status", ""),
                        evidence=item.get("evidence"),
                        source=item.get("source"))
                if st.get("lesson_status") == "ended" and not s.get("_completion_persisted"):
                    _persist_lesson_completion(sid)
                    s["_completion_persisted"] = True
        except Exception as exc:
            print(f"[persistence] 同步失败: {exc}")
        _persist(sid, st)
    return st


def _heartbeat(sid: str, stop: threading.Event) -> None:
    """心跳：每 TICK_SECONDS 把时钟推一次。

    只在课真正开始后（status == running）才推 —— 学生进教室到老师点「开始上课」
    之间不该算课时。开始之后，学生不发消息时也靠它推进：到点讲下一段、到点抛下一问、
    到点切幕。编排器不知道心跳存在，它只是收到了一个没有学生输入的轮次。
    """
    while not stop.wait(TICK_SECONDS):
        try:
            s = SESSIONS.get(sid)
            if s is None:
                return
            if s["state"].get("lesson_status") != "running":
                continue                     # 还在等上课 / 已下课，不推时钟
            st = _step(sid, "", "host", tick_only=True)
            if st.get("lesson_status") == "ended":
                return                       # 下课了，心跳自然停
        except Exception as e:               # 心跳不能把服务拖垮
            print(f"[心跳异常] {sid}: {type(e).__name__}: {e}", file=sys.stderr)


def _create_session(sid: str, student_id: str, lesson_id: str,
                    time_scale: float) -> dict:
    """学生在教室坐下：会话建好，但**不开课**（起课铃由老师的 begin 按钮按）。"""
    s = _get(sid)
    s["time_scale"] = time_scale
    s["state"].update({
        "time_scale": time_scale,
        "student_id": student_id,
        "lesson_id": lesson_id,
        "lesson_status": "idle",
    })
    _persist(sid, s["state"])

    if s["thread"] is None or not s["thread"].is_alive():
        stop = threading.Event()
        s["stop"] = stop
        t = threading.Thread(target=_heartbeat, args=(sid, stop), daemon=True)
        s["thread"] = t
        t.start()
    return s["state"]


def _begin_lesson(sid: str) -> dict:
    """起课铃：加载课程计划 → 说开场白 → 切进第一个环节，并开始计时。"""
    s = _get(sid)
    if s["state"].get("lesson_status") == "running":
        raise HTTPException(409, "这节课已经开始上课了")
    if s["state"].get("lesson_status") == "ended":
        raise HTTPException(409, "这节课已下课，请新建一个会话")

    st1 = _step(sid, "", "host", tick_only=True,
                external_event=EVENT_BEGIN, status="running")
    if st1.get("lesson_status") == "ended":
        return st1
    # 补一轮心跳，让学生立刻听到第一段内容，而不是干等第一次心跳（默认 10 秒后）。
    # ⚠️ 视频模式下这轮是静默的——别让它把起课铃的开场白覆盖成空回复。
    st2 = _step(sid, "", "host", tick_only=True)
    if not (st2.get("reply_text") or "").strip():
        st2["reply_text"] = st1.get("reply_text", "")
    return st2


def _running(sid: str) -> dict:
    """外部事件的公共前置检查：课必须正在上。"""
    s = _get(sid)
    status = s["state"].get("lesson_status")
    if status == "idle":
        raise HTTPException(409, "课堂还没开始，请先调用 /begin")
    if status == "ended":
        raise HTTPException(409, "课堂已结束")
    return s


# ═══════════════════════════════════════════════════════════════
# 接口
# ═══════════════════════════════════════════════════════════════

class StartIn(BaseModel):
    session_id: str | None = None
    student_id: str = "student-001"
    lesson_id: str = "ch3-process-scheduling"
    time_scale: float = 1.0        # >1 压缩时间：课前演练用 12 倍把 45 分钟压到 4 分钟
    launch_token: str | None = None  # 平台签发的可信启动令牌；提供时覆盖 student_id 并绑定课程上下文


class MessageIn(BaseModel):
    text: str



def _record_learning_event(sid: str, event_type: str,
                           payload: dict | None = None,
                           event_id: str | None = None) -> None:
    """把一次学习事件写入统一存储（生产=student schema，demo=runtime JSON）。"""
    s = SESSIONS.get(sid)
    if not s:
        return
    ctx = s.get("platform") or s.get("state", {}).get("platform") or {}
    if not ctx.get("userId"):
        return  # 非平台会话（demo）不入正式库
    try:
        from apps.integration import persistence
        persistence.record_event(
            session_key=sid,
            user_id=ctx["userId"],
            course_id=ctx.get("courseId", ""),
            publication_id=ctx.get("publicationId", ""),
            classroom_id=ctx.get("classroomId"),
            event_type=event_type,
            payload=payload,
            event_id=event_id or f"{event_type}-{int(time.time() * 1000)}",
        )
    except Exception as exc:  # 持久化失败不阻塞课堂，但要留痕
        print(f"[persistence] {event_type} 写入失败: {exc}")


def _persist_session_record(sid: str) -> None:
    """把会话行（首次）与消息流水同步到统一存储。"""
    s = SESSIONS.get(sid)
    if not s:
        return
    ctx = s.get("platform") or s.get("state", {}).get("platform") or {}
    if not ctx.get("userId"):
        return
    try:
        from apps.integration import persistence
        persistence.upsert_session(
            session_key=sid,
            user_id=ctx["userId"],
            course_id=ctx.get("courseId", ""),
            publication_id=ctx.get("publicationId", ""),
            publication_version=ctx.get("publicationVersion", 0),
            classroom_id=ctx.get("classroomId"),
        )
        seen = s.get("_persisted_message_seq", 0)
        messages = s.get("messages") or []
        for index, msg in enumerate(messages[seen:], start=seen + 1):
            persistence.upsert_message(
                session_key=sid,
                user_id=ctx["userId"],
                course_id=ctx.get("courseId", ""),
                publication_id=ctx.get("publicationId", ""),
                seq=index,
                role=msg.get("role", "student"),
                phase=msg.get("phase"),
                content=msg.get("text", ""),
            )
        s["_persisted_message_seq"] = len(messages)
    except Exception as exc:
        print(f"[persistence] 会话同步失败: {exc}")


def _persist_lesson_completion(sid: str) -> None:
    """Persist the final report and terminal session timestamp once."""
    s = SESSIONS.get(sid)
    if not s:
        return
    st = s.get("state") or {}
    ctx = s.get("platform") or st.get("platform") or {}
    if not ctx.get("userId"):
        return
    from apps.integration import persistence

    report = {
        "schemaVersion": 1,
        "sessionId": sid,
        "courseId": ctx.get("courseId"),
        "publicationId": ctx.get("publicationId"),
        "publicationVersion": ctx.get("publicationVersion"),
        "classroomId": ctx.get("classroomId"),
        "courseTitle": ctx.get("courseTitle"),
        "lessonElapsedMinutes": st.get("lesson_elapsed_minutes"),
        "knowledgeMastery": st.get("kp_stars") or {},
        "stageSnapshots": st.get("stage_snapshots") or [],
        "playedMedia": st.get("played_media") or [],
        "endedAt": st.get("now") or _now(),
    }
    persistence.upsert_report(
        session_key=sid,
        user_id=ctx["userId"],
        course_id=ctx.get("courseId", ""),
        publication_id=ctx.get("publicationId", ""),
        payload=report,
    )
    persistence.finish_session(sid)
    _record_learning_event(sid, event_type="lesson_ended")


@app.post("/api/session/start")
def start(body: StartIn) -> dict:
    """进教室。**不会自动上课** —— 课要等老师按「开始上课」（POST /begin）才起。

    幂等：同一个 session_id 重复调用不会重新开课。
    携带平台 launch_token 时：身份与课程上下文以令牌为准（调用方传入的
    student_id 被忽略），并把 publication version 固定进会话，教师后续
    重新发布不影响进行中的这节课。
    """
    import uuid
    platform_context = None
    learning_context = None
    student_id = body.student_id
    lesson_id = body.lesson_id
    if body.launch_token:
        from apps.integration import config as integration_config
        from apps.integration import course_adapter, launch_context, platform_client
        from apps.integration.launch_context import LaunchTokenError
        try:
            integration_config.require_platform_config()
            payload = launch_context.verify_launch_token(body.launch_token)
            learning_context = course_adapter.from_platform_payload(
                platform_client.fetch_learning_context(body.launch_token))
        except LaunchTokenError as error:
            raise HTTPException(status_code=401, detail=f"launch token 无效：{error}") from error
        except course_adapter.ContextContractError as error:
            raise HTTPException(status_code=502, detail=f"学习上下文契约错误：{error}") from error
        except platform_client.PlatformClientError as error:
            status = 503 if error.status in (0, 503) else error.status
            raise HTTPException(status_code=status, detail=str(error)) from error
        platform_context = launch_context.launch_identity(payload)
        platform_context["courseTitle"] = learning_context.course_title
        student_id = platform_context["userId"]
        requested = next((item for item in learning_context.lessons
                          if item.id == body.lesson_id), None)
        if requested:
            lesson_id = requested.id
            learning_context.classroom = requested.classroom
            if requested.classroom:
                platform_context["classroomId"] = requested.classroom.id
                platform_context["playerUrl"] = requested.classroom.player_url
        else:
            lesson_id = platform_context["courseId"]
    sid = body.session_id or f"cls-{uuid.uuid4().hex[:8]}"
    with _REGISTRY_LOCK:
        if sid not in SESSIONS:
            SESSIONS[sid] = {
                "state": initial_state(sid, student_id, lesson_id),
                "messages": [],
                "lock": threading.Lock(),
                "stop": threading.Event(),
                "thread": None,
                "time_scale": body.time_scale,
            }
    st = _create_session(sid, student_id, lesson_id, body.time_scale)
    if platform_context:
        s = _get(sid)
        s["state"]["platform"] = platform_context
        s["platform"] = platform_context
        if learning_context:
            # The orchestrator's state dict is what load_plan/judge_mastery
            # read; store a plain dict so JSON persistence and in-memory use
            # the same shape.
            s["state"]["learning_context"] = learning_context.model_dump()
            s["learning_context"] = learning_context.model_dump()
        _persist(sid, s["state"])
        _persist_session_record(sid)
        _record_learning_event(sid, event_type="session_started")
    return {
        "session_id": sid,
        "status": st.get("lesson_status"),
        "phase": st.get("host_phase"),
        "available_actions": ACTIONS[st.get("lesson_status", "idle")],
        "reply_text": "",
    }


class EventIn(BaseModel):
    type: str = ""                 # begin / media_done / next_stage（只走 /event 时必填）
    segment_id: str | None = None  # media_done 时可带上刚播完的素材 id（只记录，不强校验）
    scene_id: str | None = None
    event_id: str | None = None


@app.post("/api/session/{sid}/begin")
def begin(sid: str) -> dict:
    """★ 课堂开始。老师按「开始上课」按钮时调这个。

    这一轮会加载课程计划、说开场白、切进第一个环节并开始计时。
    """
    st = _begin_lesson(sid)
    _record_learning_event(sid, event_type="lesson_began")
    return {
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.post("/api/session/{sid}/media/done")
def media_done(sid: str, body: EventIn | None = None) -> dict:
    """★ 讲解视频播放完成 —— 前端播放器播完时调一次。

    当前课程是「整段视频」模式（lesson-plan 里 delivery=video）：
    视频全片播完报一次即可，AI 不会出讲解词，切到下一环节（复述）。
    视频播放期间时间照常计入课堂时长；讲解阶段不会因时间预算被切走。
    """
    _running(sid)
    st = _step(sid, "", "host", tick_only=True, external_event=EVENT_MEDIA_DONE)
    event = body or EventIn(type="media_done")
    s = _get(sid)
    ctx = s.get("platform") or st.get("platform") or {}
    if ctx.get("userId"):
        try:
            from apps.integration import persistence
            scene_id = event.scene_id or "__complete__"
            persistence.upsert_playback_progress(
                session_key=sid,
                user_id=ctx["userId"],
                course_id=ctx.get("courseId", ""),
                publication_id=ctx.get("publicationId", ""),
                classroom_id=ctx.get("classroomId", ""),
                scene_id=scene_id,
                segment_id=event.segment_id,
            )
            _record_learning_event(
                sid,
                event_type="media_done",
                payload={"sceneId": scene_id, "segmentId": event.segment_id},
                event_id=event.event_id or f"media_done-{scene_id}",
            )
        except Exception as exc:
            print(f"[persistence] 播放进度写入失败: {exc}")
    return {
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "advance_reason": st.get("advance_reason"),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.post("/api/session/{sid}/stage/next")
def stage_next(sid: str, body: EventIn | None = None) -> dict:
    """★ 下一环节。老师按「下一环节」按钮时调，无条件切到下一幕。

    不理会当时 Discuss：哪怕时间没到、问题没答完也会切。适合老师掌控节奏。
    """
    _running(sid)
    st = _step(sid, "", "host", tick_only=True, external_event=EVENT_NEXT_STAGE)
    return {
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.post("/api/session/{sid}/event")
def event(sid: str, body: EventIn) -> dict:
    """统一事件入口。前端只对接这一个也行：{"type": "begin"|"media_done"|"next_stage"}。"""
    if body.type == "begin":
        return begin(sid)
    if body.type == "media_done":
        return media_done(sid, body)
    if body.type == "next_stage":
        return stage_next(sid, body)
    raise HTTPException(400, f"未知事件类型：{body.type}（可选 begin / media_done / next_stage）")


@app.post("/api/session/{sid}/message")
def send(sid: str, body: MessageIn) -> dict:
    """学生发言 → 编排一轮 → 返回 AI 的回复。课没开始时调用会报 409。"""
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "消息为空")
    _running(sid)
    s = _get(sid)
    s["messages"].append({
        "seq": len(s["messages"]),
        "role": "student",
        "text": text,
        "at": _now(),
        "phase": s["state"].get("host_phase"),
    })
    st = _step(sid, text, "student")
    _record_learning_event(sid, event_type="student_message",
                           payload={"phase": st.get("host_phase")})
    return {
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.get("/api/session/{sid}/messages")
def messages(sid: str, since: int = 0) -> dict:
    """增量拉取。心跳说的话也在这里出现（界面定期轮询即可）。"""
    s = _get(sid)
    return {
        "messages": s["messages"][since:],
        "total": len(s["messages"]),
        "student_id": s["state"].get("student_id"),
    }


@app.get("/api/session/{sid}/state")
def state(sid: str) -> dict:
    """当前状态。前端照 `available_actions` 渲染按钮，不用自己猜能不能按。"""
    s = _get(sid)
    st = s["state"]
    status = st.get("lesson_status", "idle")
    plan = st.get("lesson_plan") or {}
    total_seg = len(plan.get("segments") or [])
    return {
        "status": status,
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "stage_elapsed_minutes": st.get("stage_elapsed_minutes"),
        "stage_budget_minutes": st.get("stage_budget_minutes"),
        "lesson_elapsed_minutes": st.get("lesson_elapsed_minutes"),
        "total_minutes": plan.get("total_minutes"),
        "current_question": st.get("current_question"),
        "advance_reason": st.get("advance_reason"),
        "student_status": st.get("student_status"),
        "time_scale": s["time_scale"],
        "stars": st.get("kp_stars") or {},
        # 讲解素材进度：第几段 / 共几段，播完几段
        "segment_cursor": st.get("segment_cursor", 0),
        "segment_total": total_seg,
        "played_media": st.get("played_media") or [],
        "remaining_stages": st.get("remaining_stages") or [],
        "next_stage": (st.get("remaining_stages") or [None])[0],
        "available_actions": ACTIONS.get(status, []),
    }


@app.delete("/api/session/{sid}")
def stop(sid: str) -> dict:
    """停课：下课或老师主动结束。落盘的状态保留，仍可导出学情。"""
    with _REGISTRY_LOCK:
        s = SESSIONS.get(sid)
        if s:
            s["stop"].set()
            s["state"]["lesson_status"] = "ended"
            _persist(sid, s["state"])
            if not s.get("_completion_persisted"):
                _persist_lesson_completion(sid)
                s["_completion_persisted"] = True
    return {"stopped": True, "status": "ended", "available_actions": ACTIONS["ended"]}


@app.get("/api/session/{sid}/export")
def export(sid: str, fmt: str = "md") -> Response:
    """课后学情导出。md 给人读，json 给系统读。"""
    st = _get(sid)["state"]
    stars = st.get("kp_stars") or {}
    snaps = st.get("stage_snapshots") or []
    plan = st.get("lesson_plan") or {}
    student_id = st.get("student_id")
    lesson_id = st.get("lesson_id")

    if fmt == "json":
        return Response(
            content=json.dumps({
                "student_id": student_id, "lesson_id": lesson_id,
                "session_id": sid,
                "lesson_elapsed_minutes": st.get("lesson_elapsed_minutes"),
                "knowledge_points": [
                    {"kp_id": kp, "title": kp_title(kp), "stars": v,
                     "status": STAR_STATUS.get(v, "未检测")}
                    for kp, v in sorted(stars.items())
                ],
                "stage_snapshots": snaps,
            }, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{sid}.json"'},
        )

    weak = [(kp, v) for kp, v in sorted(stars.items()) if v <= 2]
    lines = [
        f"# 学情报告 · {plan.get('lesson_title', lesson_id)}",
        "",
        f"- 学生：{student_id}",
        f"- 会话：{sid}",
        f"- 计划时长：{plan.get('total_minutes')} 分钟"
        f"｜实际：{st.get('lesson_elapsed_minutes')} 分钟",
        f"- 导出时间：{_now()}",
        "",
        "## 知识点掌握",
        "",
        "| 知识点 | 星级 | 状态 |",
        "| --- | --- | --- |",
    ]
    for kp, v in sorted(stars.items()):
        lines.append(f"| {kp} {kp_title(kp)} | {'★' * v or '—'} | "
                     f"{STAR_STATUS.get(v, '未检测')} |")
    if snaps:
        lines += ["", "## 各阶段表现", "",
                  "| 阶段 | 用时(分) | 关闭目标 | 未关闭目标 |", "| --- | --- | --- | --- |"]
        for snap in snaps:
            lines.append(
                f"| {STAGE_NAMES.get(snap.get('stage'), snap.get('stage'))} "
                f"| {snap.get('stage_elapsed_minutes')} "
                f"| {len(snap.get('targets_closed') or [])} "
                f"| {len(snap.get('targets_open') or [])} |"
            )
    lines += ["", "## 课后建议", ""]
    if weak:
        for kp, v in weak:
            lines.append(f"- **{kp_title(kp)}**（{kp}，{'★' * v or '0 星'}）："
                         f"课上未达到理解线，建议先回到对应片段重听。")
    else:
        lines.append("- 全部知识点达到理解线以上，可以做进阶练习。")
    md = "\n".join(lines)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{sid}.md"'},
    )


@app.get("/api/session/{sid}/stars")
def stars(sid: str) -> dict:
    """课堂内按知识点看掌握度，形状与 /export 的 knowledge_points 一致。

    为什么单独开一个：/state 的 stars 是 {"KP-001": 3} 这种裸 map，只有内部编号；
    而 MASTERY-STAR-RULES.md 要求「不能把 KP-004 这类内部编号说给学生听」。
    这里用 kp_title() 换成中文标题，前端上课时每几秒轮询一次即可。
    """
    st = _get(sid)["state"]
    return {
        "knowledge_points": [
            {"kp_id": kp, "title": kp_title(kp), "stars": v,
             "status": STAR_STATUS.get(v, "未检测")}
            for kp, v in sorted((st.get("kp_stars") or {}).items())
        ]
    }


@app.get("/api/session/demo-flag")
def demo_flag() -> dict:
    """前端探测后端是否处于显式 demo 模式（仅此时允许加载内置演示课）。"""
    from apps.integration import config as integration_config
    return {"demoMode": integration_config.demo_mode()}


def _preload_disk_sessions() -> None:
    """重启后把磁盘上的会话加载回内存注册表（_get 是惰性的，不主动扫就不会加载）。"""
    import glob
    for path_str in glob.glob(str(SESSIONS_DIR / "*.json")):
        sid = Path(path_str).stem
        with _REGISTRY_LOCK:
            if sid not in SESSIONS:
                state = _restore(sid)
                if state:
                    SESSIONS[sid] = {
                        "state": state,
                        "messages": [],
                        "lock": threading.Lock(),
                        "stop": threading.Event(),
                        "thread": None,
                        "time_scale": state.get("time_scale", 1.0),
                    }


def _session_courses_payload(session_id: str = "") -> list:
    """课程目录：按会话注册表里的 learning_context 聚合（正式链路）。

    会话在 /start 时已锁定发布版本，这里复用同一上下文，保证前端
    看到的课程与正在进行的会话一致。
    """
    _preload_disk_sessions()
    courses: dict = {}
    with _REGISTRY_LOCK:
        snapshot = ([(session_id, SESSIONS[session_id])] if session_id and session_id in SESSIONS
                    else ([] if session_id else list(SESSIONS.items())))
    for sid, session in snapshot:
        # Read from state (survives restarts via _restore), not the wrapper.
        state = session.get("state") or session
        context = (state.get("learning_context") if isinstance(state, dict) else None) or session.get("learning_context")
        if not context:
            continue
        if isinstance(context, dict):
            from apps.integration.models import CourseLearningContext as _M
            try:
                context = _M(**context)
            except Exception:
                continue
        course = courses.setdefault(context.course_id, {
            "courseId": context.course_id,
            "name": context.course_title or context.course_id,
            "summary": context.knowledge_package.summary or "",
            "icon": "◆",
            "currentWeek": max((lesson.order for lesson in context.lessons), default=1),
            "lessons": [],
        })
        seen_lesson_ids = {item["lessonId"] for item in course["lessons"]}
        for lesson in context.lessons:
            if lesson.id in seen_lesson_ids:
                continue
            seen_lesson_ids.add(lesson.id)
            course["lessons"].append({
                "lessonId": lesson.id,
                "week": lesson.order,
                "chapter": f"第 {lesson.order} 章",
                "title": lesson.title,
                "summary": context.knowledge_package.summary or "",
                "status": "current",
                "estimatedMinutes": max(20, 5 * len(lesson.segments)),
                "knowledgePoints": [kp.title for kp in context.evaluation.knowledge_points],
            })
    return list(courses.values())


@app.get("/api/session/courses")
def session_courses(sessionId: str = "") -> list:
    courses = _session_courses_payload(sessionId)
    if sessionId and not courses:
        raise HTTPException(status_code=404, detail="未找到当前学习会话的课程上下文")
    return courses


@app.get("/api/session/lesson")
def session_lesson(lessonId: str = "", sessionId: str = "") -> dict:
    """课时信息：从会话的 learning_context 取对应 lesson（正式链路）。"""
    _preload_disk_sessions()
    with _REGISTRY_LOCK:
        snapshot = ([(sessionId, SESSIONS[sessionId])] if sessionId and sessionId in SESSIONS
                    else ([] if sessionId else list(SESSIONS.items())))
    for sid, session in snapshot:
        # Read from state (survives restarts via _restore), not the wrapper.
        state = session.get("state") or session
        context = (state.get("learning_context") if isinstance(state, dict) else None) or session.get("learning_context")
        if not context:
            continue
        if isinstance(context, dict):
            from apps.integration.models import CourseLearningContext as _M
            try:
                context = _M(**context)
            except Exception:
                continue
        for lesson in context.lessons:
            if not lessonId or lesson.id == lessonId:
                return {
                    "lessonId": lesson.id,
                    "course": context.course_title,
                    "chapter": "第 1 章",
                    "title": lesson.title,
                    "summary": context.knowledge_package.summary or "",
                    "estimatedMinutes": max(20, 5 * len(lesson.segments)),
                    "knowledgePointCount": len(context.evaluation.knowledge_points),
                    "segmentCount": len(lesson.segments),
                    "knowledgePoints": [kp.title for kp in context.evaluation.knowledge_points],
                    "segments": [
                        {"segmentId": seg.id, "title": seg.title, "order": seg.order,
                         "startSeconds": 0, "endSeconds": 0}
                        for seg in lesson.segments
                    ],
                    "classroomId": context.classroom.id if context.classroom else None,
                    "playerUrl": context.classroom.player_url if context.classroom else "",
                }
    raise HTTPException(status_code=404, detail="未找到该课时的学习上下文（请从平台进入）")


@app.get("/api/session/health")
def session_health() -> dict:
    """平台探活端点（student_bridge 的 studentAgentReady 检查）。"""
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ═══════════════════════════════════════════════════════════════
# 前端（Next.js 学生端）

# 源码在 frontend/，构建产物同步到 apps/static/app/。
# 挂在跟 /api 同一个源下，浏览器不认为是跨域，所以**不需要 CORS**。
# 构建：cd frontend && npm run build，再把 out/ 拷到 apps/static/app/
# ═══════════════════════════════════════════════════════════════

FRONTEND_DIR = STATIC_DIR / "app"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/app")
def frontend_index() -> FileResponse:
    """单独接一个无斜杠路径 —— 只靠挂载点时 /app 不一定会跳到 /app/。"""
    page = FRONTEND_DIR / "index.html"
    if not page.is_file():
        raise HTTPException(
            404,
            "前端还没构建。先在 frontend/ 里跑 npm run build，"
            "再把 out/ 同步到 apps/static/app/（或直接跑根目录的 构建前端.cmd）",
        )
    return FileResponse(page)


app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("AGENT_PORT", "8000")), log_level="info")
