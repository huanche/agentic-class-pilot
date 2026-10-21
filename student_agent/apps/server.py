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

import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

from agent import (  # noqa: E402
    EVENT_BEGIN, EVENT_MEDIA_DONE, EVENT_NEXT_STAGE, EVENT_END_LESSON,
    STAGE_NAMES, STAR_STATUS, build_graph, initial_state,
    knowledge_catalog_public, kp_title, run_turn_stateless,
    tutoring_feedback_payload, tutoring_public,
)
from llm_override import set_llm_override  # noqa: E402
from apps.integration.data_cleanup import without_self_assessment  # noqa: E402
from apps.integration.mastery import normalize_mastery_state  # noqa: E402

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    raise SystemExit("缺依赖：pip install fastapi uvicorn")


TICK_SECONDS = float(os.environ.get("AGENT_TICK_SECONDS", "10"))
SESSIONS_DIR = ROOT / "runtime" / "sessions"
STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_OUT_DIR = ROOT / "frontend" / "out"

# 会话状态 → 此刻前端该显示哪些按钮（前端照着这个渲染，不要自己猜能不能按）
ACTIONS = {
    "idle": ["begin"],                                  # 已进教室，等老师点「开始上课」
    "running": ["message", "media_done", "next_stage", "end", "stop"],
    "ended": ["export"],
}

GRAPH = build_graph()          # 不带 checkpointer：状态由本模块持有并回灌

# sid -> {"state": dict, "messages": [...], "lock": Lock, "stop": Event, "thread": Thread}
SESSIONS: dict[str, dict] = {}
_REGISTRY_LOCK = threading.Lock()

app = FastAPI(title="主动引导智能体 · 会话层")
# CORS：默认仅放行本机调试来源；跨域部署时设 AGENT_CORS_ORIGIN_REGEX 为真实来源
# （正则，如 https://(www\.)?example\.com$，多个用 | 连接）。网关同源反代不经过此处。
CORS_ORIGIN_REGEX = os.environ.get("AGENT_CORS_ORIGIN_REGEX") or r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════════════════════════

def _now() -> str:
    """会话层负责取时间，图里不许自己读时钟 —— 这样编排逻辑才可单测、可回放。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


# session_id 来自请求体，却会被直接拼进文件名 —— 必须白名单。
# 实测（2026-09-22）：不加这道校验时，POST /api/session/start 传
# "../../pwned" 会把 json 写到仓库根目录，且全程无需任何凭证。
# 只放行字母数字与 . _ -，首字符必须字母数字，拦住 ../、绝对路径、盘符。
_SID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _safe_sid(sid: str) -> str:
    """校验 session_id 能安全用作文件名，非法则 400。"""
    if not _SID_RE.match(sid or ""):
        raise HTTPException(
            400, f"非法会话号：{sid!r}（只允许字母数字与 . _ -，以字母数字开头）"
        )
    return sid


def _path(sid: str) -> Path:
    return SESSIONS_DIR / f"{_safe_sid(sid)}.json"


def _persist(sid: str, state: dict) -> None:
    normalize_mastery_state(state)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _path(sid).write_text(
        json.dumps(without_self_assessment(state), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _restore(sid: str) -> dict | None:
    """进程重启后从磁盘续上。旧文件可能缺新字段，用 initial_state 兜底。"""
    p = _path(sid)
    if not p.is_file():
        return None
    try:
        saved = without_self_assessment(json.loads(p.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return None
    merged = initial_state(sid)
    merged.update(saved)
    return normalize_mastery_state(merged)


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
        # 平台个人模型配置（BYOK）：每个会话只在第一轮拉取一次，
        # 失败/未配置回退 AGENT_LLM_* 环境变量；仅对本轮线程生效。
        if "platform" in s and "llm_override_loaded" not in s:
            s["llm_override_loaded"] = True
            uid = (s.get("platform") or {}).get("userId")
            if uid:
                from apps.integration import platform_client
                cfg = platform_client.fetch_user_model_config(str(uid))
                if cfg:
                    s["llm_override"] = cfg
                    print(f"[BYOK] 会话 {sid} 启用用户 {uid} 的个人模型配置 "
                          f"({(cfg.get('llm') or {}).get('model', '?')})", file=sys.stderr)
        set_llm_override(s.get("llm_override"))
        try:
            st = run_turn_stateless(
                GRAPH, s["state"], _now(), message, speaker,
                tick_only=tick_only, time_scale=s["time_scale"],
                external_event=external_event,
            )
        finally:
            set_llm_override(None)

        # 这一轮跑的这几秒里，会话可能已经被停掉了 —— 老师按了「停课」
        # （DELETE 会置 stop 并把 ended 落盘），或者进程/测试把它从注册表里摘了。
        # 那种情况下**整轮结果作废**：既不更新内存状态也不落盘。
        #
        # 少了这道闸，在飞的心跳轮次结束时会用 running 盖掉刚刚写下的 ended ——
        # 于是停课被静默撤销，进程重启后 _restore 看到 running 还会自动接着上课。
        # 实测：接入真实大模型后一轮要好几秒，这个窗口很容易撞上（本地跑测试
        # 就稳定复现了：tearDown 删掉的会话文件 3 秒后自己长了回来）。
        stop_event = s.get("stop")
        if (stop_event is not None and stop_event.is_set()) or SESSIONS.get(sid) is not s:
            return st

        # 下课：advance_stage 置 student_status=ended 那一刻，课就算结束
        if st.get("host_phase") == "ending" and st.get("student_status") == "ended":
            st["lesson_status"] = "ended"
        for extra in ("platform", "learning_context"):
            if extra in s and extra not in st:
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
        for extra in ("platform", "learning_context"):
            if extra in s:
                st[extra] = s[extra]
        # 学习数据同步到 student schema（幂等；ctx 从 state 读，重启可恢复；
        # 放在消息 append 之后，保证本轮 AI 回复也被记录；失败不阻塞课堂）
        try:
            ctx = st.get("platform") or {}
            if ctx.get("userId"):
                from apps.integration import persistence
                # 两个标记分工：_persisted_message_count = 内存里已同步的条数；
                # _persisted_message_seq = 库里最后写到的编号。会话被重建
                # （同 key 重新 start）后两者不再相等——库里已有旧消息时，
                # 新消息若从 seq 1 编起会被 (session_key, seq) 幂等键静默
                # 吞掉，所以首sync先读库里的最大 seq 接着编。
                last_seq = s.get("_persisted_message_seq")
                if last_seq is None:
                    try:
                        last_seq = persistence.max_message_seq(sid)
                    except Exception:
                        last_seq = 0
                messages = s.get("messages") or []
                done = s.get("_persisted_message_count", 0)
                for msg in messages[done:]:
                    last_seq += 1
                    persistence.upsert_message(
                        session_key=sid, user_id=ctx["userId"],
                        course_id=ctx.get("courseId", ""),
                        publication_id=ctx.get("publicationId", ""),
                        seq=last_seq, role=msg.get("role", "student"),
                        phase=msg.get("phase") or st.get("host_phase"),
                        content=msg.get("text", ""))
                s["_persisted_message_seq"] = last_seq
                s["_persisted_message_count"] = len(messages)
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


# ═══════════════════════════════════════════════════════════════
# 平台集成：学情写入统一存储
#
# 仅平台会话（s["platform"] 有 userId）写正式库；独立 demo 会话直接返回。
# 全部失败均不阻塞课堂 —— 课堂可用性优先于学情完整性，失败留痕到 stdout。
# 详见 PLATFORM-INTEGRATION.md。
# ═══════════════════════════════════════════════════════════════

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


def _record_tutoring_event(sid: str, event_type: str, payload: dict) -> None:
    """辅导的出题/判答事件：平台会话进 learning_events；
    demo 会话（STUDENT_DEMO_MODE=true）走同一份 record_event 落 runtime JSON。
    独立态（既非平台也没开 demo）不落盘——事件随会话 state 一起在
    runtime/sessions 里，仍可追溯。"""
    s = SESSIONS.get(sid)
    if not s:
        return
    ctx = s.get("platform") or s.get("state", {}).get("platform") or {}
    if ctx.get("userId"):
        _record_learning_event(sid, event_type, payload)
        return
    try:
        from apps.integration import config as integration_config
        from apps.integration import persistence
        if not integration_config.demo_mode():
            return
        persistence.record_event(
            session_key=sid, user_id="demo", course_id="", publication_id="",
            event_type=event_type, payload=payload,
            event_id=f"{event_type}-{int(time.time() * 1000)}",
        )
    except Exception as exc:  # 持久化失败不阻塞课堂，但要留痕
        print(f"[persistence] {event_type} demo 写入失败: {exc}")


def _generate_tutoring_feedback(sid: str, trigger_text: str, st: dict) -> None:
    """学生明确结束课后辅导：生成完整反馈并入库（多版本，只增不改）。

    平台态/演示态走 append_report_version；独立态（无库无 demo）尽力而为：
    写库失败不拦下课，反馈留在会话缓存里（素材随会话 state 落盘）。
    教师视角摘要一并入库（本次不建教师端页面）。
    """
    payload, teacher_summary = tutoring_feedback_payload(st, trigger_text)
    s = SESSIONS.get(sid)
    ctx = (s.get("platform") if s else None) or (st.get("platform") or {})
    reports = (s or {}).get("tutoring_reports") or []
    version = len(reports) + 1
    try:
        from apps.integration import persistence
        version = persistence.append_report_version(
            session_key=sid, user_id=ctx.get("userId", "demo"),
            course_id=ctx.get("courseId", ""), publication_id=ctx.get("publicationId", ""),
            payload=payload, teacher_summary=teacher_summary)
    except Exception as exc:  # 持久化失败不拦下课，但要留痕
        print(f"[persistence] 辅导反馈写入失败: {exc}")
    if s is not None:
        s["tutoring_reports"] = reports + [{
            "version": version, "payload": payload,
            "teacher_summary": teacher_summary,
        }]
    _record_tutoring_event(sid, "tutoring_feedback", {
        "version": version, "trigger": payload.get("trigger"),
        "actual_minutes": payload.get("actual_minutes"),
    })


def _notify_platform_progress(sid: str, event: str) -> None:
    """课堂开始/结束时通知平台，由平台把学情同步到教师端授课管理（尽力而为）。"""
    s = SESSIONS.get(sid)
    if not s:
        return
    ctx = s.get("platform") or s.get("state", {}).get("platform") or {}
    if not ctx.get("userId") or not ctx.get("courseId"):
        return  # 非平台会话（demo）无需同步
    try:
        from apps.integration import platform_client
        platform_client.post_learning_progress(
            user_id=str(ctx["userId"]), course_id=str(ctx["courseId"]),
            session_key=sid, classroom_id=ctx.get("classroomId"), event=event)
    except Exception as exc:  # 通知失败不影响上课
        print(f"[persistence] 学习进度通知失败: {exc}")


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
    _notify_platform_progress(sid, "ended")


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
    time_scale: float = 1.0
    launch_token: str


class MessageIn(BaseModel):
    text: str

@app.post("/api/session/start")
def start(body: StartIn) -> dict:
    """进教室。**不会自动上课** —— 课要等老师按「开始上课」（POST /begin）才起。

    幂等：同一个 session_id 重复调用不会重新开课。
    携带平台 launch_token 时：身份与课程上下文**以令牌为准**（调用方传入的
    student_id 被忽略），并把 publication version 固定进会话，教师后续
    重新发布不影响进行中的这节课。
    """
    import uuid
    platform_context = None
    learning_context = None
    if not body.launch_token:
        raise HTTPException(status_code=401, detail="请从课程平台进入")
    student_id = ""
    lesson_id = ""
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
                          if item.id == getattr(body, "lesson_id", "")), None)
        if requested:
            lesson_id = requested.id
            learning_context.classroom = requested.classroom
            if requested.classroom:
                platform_context["classroomId"] = requested.classroom.id
                platform_context["playerUrl"] = requested.classroom.player_url
        else:
            lesson_id = platform_context["courseId"]

    # 先校验再动注册表，非法 id 不该留下任何痕迹（_path 里还有一道兜底）
    if body.session_id:
        sid = _safe_sid(body.session_id)
    elif platform_context and lesson_id:
        # 平台态：会话号由（用户, 课程, 课时）确定性派生 —— 换设备/换浏览器后
        # 再进同一课时，落回**同一个**辅导会话（磁盘可恢复），而不是新开一个。
        digest = hashlib.sha1("|".join([
            str(platform_context.get("userId") or ""),
            str(platform_context.get("courseId") or ""),
            str(lesson_id),
        ]).encode("utf-8")).hexdigest()[:16]
        sid = f"plat-{digest}"
    else:
        sid = f"cls-{uuid.uuid4().hex[:8]}"
    created = False
    with _REGISTRY_LOCK:
        if sid not in SESSIONS:
            restored = _restore(sid)
            state = restored or initial_state(sid, student_id, lesson_id)
            SESSIONS[sid] = {
                "state": state,
                "messages": [],
                "lock": threading.Lock(),
                "stop": threading.Event(),
                "thread": None,
                "time_scale": float(state.get("time_scale") or body.time_scale),
            }
            if platform_context:
                # 平台上下文挂在会话包装层，_step 每轮回注进 state
                SESSIONS[sid]["platform"] = platform_context
                if learning_context:
                    SESSIONS[sid]["learning_context"] = learning_context.model_dump()
            created = restored is None
        s = SESSIONS[sid]
    st = s["state"]
    if st.get("lesson_id") not in (None, lesson_id):
        raise HTTPException(409, "该会话属于另一节课")
    if st.get("student_id") not in (None, student_id):
        raise HTTPException(409, "该会话属于另一名学生")
    if created or st.get("lesson_status") in (None, "idle"):
        st = _create_session(sid, student_id, lesson_id, body.time_scale)
    elif st.get("lesson_status") == "running" and (
        s["thread"] is None or not s["thread"].is_alive()
    ):
        stop = threading.Event()
        s["stop"] = stop
        thread = threading.Thread(target=_heartbeat, args=(sid, stop), daemon=True)
        s["thread"] = thread
        thread.start()
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
            # 老版本漏转课时知识点类型，进行中的计划可能缓存了空目录。
            # 同发布版重入只补知识点，不重开课或重置学生学情。
            with s["lock"]:
                course_adapter.repair_empty_knowledge_catalog(s["state"])
        _persist(sid, s["state"])
        _persist_session_record(sid)
        _record_learning_event(sid, event_type="session_started")
    return {
        "ok": True,
        "session_id": sid,
        "status": st.get("lesson_status"),
        "phase": st.get("host_phase"),
        "available_actions": ACTIONS[st.get("lesson_status", "idle")],
        "reply_text": "",
    }


class EventIn(BaseModel):
    type: str = ""                 # begin / media_done / next_stage（只走 /event 时必填）
    segment_id: str | None = None  # media_done 时可带上刚播完的素材 id（只记录，不强校验）
    scene_id: str | None = None    # 平台播放器报上来的场景 id：学情按场景幂等记进度
    event_id: str | None = None    # 播放器事件 id：同一事件重复上报时幂等
    final: bool = True             # False 只记单页进度；True 才结束整段视频并推进阶段


@app.post("/api/session/{sid}/begin")
def begin(sid: str) -> dict:
    """★ 课堂开始。老师按「开始上课」按钮时调这个。

    这一轮会加载课程计划、说开场白、切进第一个环节并开始计时。
    """
    st = _begin_lesson(sid)
    _record_learning_event(sid, event_type="lesson_began")
    _notify_platform_progress(sid, "started")
    return {
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "current_question": st.get("current_question"),
        "total": len(_get(sid)["messages"]),
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
    if body is not None and not body.final:
        st = _get(sid)["state"]
    else:
        st = _step(sid, "", "host", tick_only=True, external_event=EVENT_MEDIA_DONE)
    # 平台链路：记录播放进度（幂等键 = scene/segment），教师端据此看"看到哪了"
    s = _get(sid)
    ctx = s.get("platform") or st.get("platform") or {}
    if ctx.get("userId"):
        try:
            from apps.integration import persistence
            segment_id = body.segment_id if body else None
            # 平台播放器按场景上报（SCENE_COMPLETED 带 sceneId）；没有时退化成整段完成。
            # 幂等键是 (session_key, scene_id)，所以 scene_id 必须逐场景不同，
            # 否则平台侧"看到哪一页"会退化成每会话一行。
            scene_id = (body.scene_id if body else None) or segment_id or "__complete__"
            persistence.upsert_playback_progress(
                session_key=sid, user_id=ctx["userId"],
                course_id=ctx.get("courseId", ""),
                publication_id=ctx.get("publicationId", ""),
                classroom_id=ctx.get("classroomId", ""),
                scene_id=scene_id, segment_id=segment_id)
            _record_learning_event(sid, event_type="media_done",
                payload={"sceneId": scene_id, "segmentId": segment_id},
                event_id=(body.event_id if body else None) or f"media_done-{scene_id}")
        except Exception as exc:
            print(f"[persistence] 播放进度写入失败: {exc}")
    return {
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "advance_reason": st.get("advance_reason"),
        "current_question": st.get("current_question"),
        "total": len(_get(sid)["messages"]),
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
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "current_question": st.get("current_question"),
        "total": len(_get(sid)["messages"]),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.post("/api/session/{sid}/end")
def end_lesson(sid: str, body: EventIn | None = None) -> dict:
    """★ 结束本节课。学生/老师按「结束本节课」时调，直接进 ending（跳过剩余阶段）。

    对应深入思考等阶段的「结束本节课」按钮。是否已满最短幕时长由前端按钮挡一道
    （与复述阶段「进入下一阶段」按钮同款 2 分钟门槛），后端无条件下课。
    """
    _running(sid)
    st = _step(sid, "", "host", tick_only=True, external_event=EVENT_END_LESSON)
    return {
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "current_question": st.get("current_question"),
        "total": len(_get(sid)["messages"]),
        "available_actions": ACTIONS[st.get("lesson_status", "running")],
    }


@app.post("/api/session/{sid}/event")
def event(sid: str, body: EventIn) -> dict:
    """统一事件入口。前端只对接这一个也行：{"type": "begin"|"media_done"|"next_stage"|"end_lesson"}。"""
    if body.type == "begin":
        return begin(sid)
    if body.type == "media_done":
        return media_done(sid, body)
    if body.type == "next_stage":
        return stage_next(sid, body)
    if body.type == "end_lesson":
        return end_lesson(sid, body)
    raise HTTPException(400, f"未知事件类型：{body.type}（可选 begin / media_done / next_stage / end_lesson）")


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
    # 本轮跑之前拍快照：_step 结束后拿新值和这两项对比，才知道这一轮
    # 发生了什么事件——出了新检测题（题变了）、学生明确结束（阶段从
    # tutoring 切到 ending）。快照丢了，事件判定就没了依据。
    state_before = s["state"]
    prev_tutoring_question = state_before.get("tutoring_question")
    prev_phase = state_before.get("host_phase")
    st = _step(sid, text, "student")
    _record_learning_event(sid, event_type="student_message",
                           payload={"phase": st.get("host_phase")})
    # 辅导的出题/判答证据（工单 03）：新题出现记 tutoring_question，
    # 本轮判出结果记 tutoring_answer（含提示标记与升星后星级）
    new_question = st.get("tutoring_question")
    if new_question and new_question != prev_tutoring_question:
        _record_tutoring_event(sid, "tutoring_question", {
            "kp_id": new_question.get("kp_id"),
            "question": new_question.get("question", ""),
            "hint_given": bool(new_question.get("hint_given")),
            "asked_at": new_question.get("asked_at"),
        })
    judged = st.get("tutoring_last_judgement")
    if judged:
        _record_tutoring_event(sid, "tutoring_answer", judged)
    # 明确结束（工单 05）：tutoring → ending 的那次切换生成完整反馈并入库。
    # 只认切换那一轮——后续在 ending 里再说「结束」不会重复入库（幂等），
    # 再次生成要等工单 06 的返回续聊把阶段拉回 tutoring 之后。
    if prev_phase == "tutoring" and st.get("host_phase") == "ending":
        _generate_tutoring_feedback(sid, text, st)
    return {
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "current_question": st.get("current_question"),
        "stars": st.get("kp_stars") or {},
        "mastery_schema": "knowledge-mastery/2",
        "needs_review": st.get("mastery_needs_review") or [],
        "total": len(s["messages"]),
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


def _video_skip_allowed() -> bool:
    """本地测试开关（工单 07）：教师端播放器不可用时允许学生端替它补上
    「视频已播完」事件。生产默认关——这不是课堂退出按钮，触发的就是
    同一个 media/done 完成事件，只在放视频这一步、且开关开启时出现。"""
    return os.environ.get("AGENT_ALLOW_VIDEO_SKIP", "").strip().lower() in (
        "1", "true", "yes", "on")


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
        "updated_at": st.get("now"),
        "time_scale": s["time_scale"],
        "stars": st.get("kp_stars") or {},
        # 讲解素材进度：第几段 / 共几段，播完几段
        "segment_cursor": st.get("segment_cursor", 0),
        "segment_total": total_seg,
        "played_media": st.get("played_media") or [],
        "remaining_stages": st.get("remaining_stages") or [],
        "next_stage": (st.get("remaining_stages") or [None])[0],
        # 本地测试：视频页显示「当作已播完」按钮（工单 07，生产默认关）
        "video_skip_allowed": _video_skip_allowed(),
        "mastery_schema": "knowledge-mastery/2",
        "needs_review": st.get("mastery_needs_review") or [],
        # 固定编号知识点目录（任何阶段都在）：下课页等展示用，与辅导同源
        "knowledge_points": knowledge_catalog_public(st),
        # 课后辅导：固定编号目录 + 复习顺序 + 时间预算（掌握条的渲染依据）
        "tutoring": tutoring_public(st, _now(), s.get("time_scale", 1.0))
        if st.get("host_phase") == "tutoring" else None,
        "available_actions": ACTIONS.get(status, []),
    }


@app.post("/api/session/{sid}/resume-tutoring")
def resume_tutoring(sid: str) -> dict:
    """返回原辅导会话继续聊（工单 06）。

    明确结束过的课后辅导可以重新打开：计划时间戳、星级、证据、已见题、
    消息全部保留；再次明确结束会生成新版反馈（旧版可查）。
    """
    s = _get(sid)
    with s["lock"]:
        st = s["state"]
        # 「进过辅导」的判据：计划时间戳在进辅导那一刻必然设置（默认时长），
        # 学生开场就结束（没出过题、没报过顺序）也算进过。
        has_tutoring = bool(st.get("tutoring_planned_end_at"))
        if st.get("host_phase") != "ending" or not has_tutoring:
            raise HTTPException(409, "当前没有可恢复的课后辅导")
        st["host_phase"] = "tutoring"
        st["student_status"] = "active"
        if st.get("lesson_status") == "ended":
            st["lesson_status"] = "running"
        # 结束确认标记是回合级的一次性状态，恢复时不许残留（否则一开口就下课）
        st["tutoring_end_confirm_pending"] = False
        st["tutoring_end_confirmed"] = False
        # 旧会话的 state 没有 active 键：用挂起题回填（高亮依据）
        if not st.get("tutoring_active_kp") and st.get("tutoring_question"):
            st["tutoring_active_kp"] = st["tutoring_question"].get("kp_id")
        st["stage_started_at"] = _now()
        s["_completion_persisted"] = False
        if s["thread"] is None or not s["thread"].is_alive() or s["stop"].is_set():
            s["stop"] = threading.Event()
            s["thread"] = threading.Thread(target=_heartbeat, args=(sid, s["stop"]), daemon=True)
            s["thread"].start()
        s["state"] = st
        _persist(sid, st)
    return {"ok": True, "phase": "tutoring", "status": st.get("lesson_status")}


def _current_mastery_report(st: dict, report: dict) -> dict:
    """最新反馈展示当前唯一掌握记录，续聊后不再混用旧版报告星级。"""
    current, teacher_summary = tutoring_feedback_payload(st)
    return {**report, "teacher_summary": teacher_summary, "payload": {**report["payload"],
        "schema": "tutoring-feedback/2",
        "knowledge_points": current["knowledge_points"], "advice": current["advice"],
        "mastery_schema": "knowledge-mastery/2"}}


@app.get("/api/session/{sid}/tutoring-report")
def tutoring_report(sid: str) -> dict:
    """课后辅导反馈（最新版）：课后页与课程级入口的展示数据。"""
    s = _get(sid)
    cached = s.get("tutoring_reports") or []
    if cached:
        last = cached[-1]
        return _current_mastery_report(s["state"], {
            "version": last["version"], "payload": without_self_assessment(last["payload"]),
            "teacher_summary": last["teacher_summary"]})
    try:
        from apps.integration import persistence
        report = persistence.read_latest_report(sid)
        if report:
            return _current_mastery_report(s["state"], report)
    except Exception as exc:  # 读取失败按没有处理，不拦展示
        print(f"[persistence] 辅导反馈读取失败: {exc}")
    raise HTTPException(status_code=404, detail="暂无课后辅导反馈")


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
    stars = {item["kp_id"]: int((st.get("kp_stars") or {}).get(item["kp_id"], 0))
             for item in knowledge_catalog_public(st)}
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
                    {"kp_id": kp, "title": kp_title(kp, lesson_id), "stars": v,
                     "status": STAR_STATUS.get(v, "未检测"),
                     "needs_review": kp in (st.get("mastery_needs_review") or [])}
                    for kp, v in sorted(stars.items())
                ],
                "stage_snapshots": snaps,
            }, ensure_ascii=False, indent=2),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{sid}.json"'},
        )

    weak = [(kp, v) for kp, v in sorted(stars.items()) if v <= 2]
    lines = [
        f"# 学情报告 · {plan.get('lesson_title') or plan.get('title') or '学情报告'}",
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
        lines.append(f"| {kp} {kp_title(kp, lesson_id)} | {'★' * v or '—'} | "
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
            lines.append(f"- **{kp_title(kp, lesson_id)}**（{kp}，{'★' * v or '0 星'}）："
                         f"课上未达到理解线，建议先回到对应片段重听。")
    else:
        lines.append("- 全部知识点达到理解线以上，可以做进阶练习。")
    md = "\n".join(lines)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{sid}.md"'},
    )


# ═══════════════════════════════════════════════════════════════
# 平台入口（platform-integration）
#
# 平台经 Caddy 把 /app* 与 /api/session/* 转发到本服务，学生用平台签发的
# launch token 进入。下面这些端点让前端能按平台下发的 learning_context
# 渲染课程与课时，而不依赖本系统自建的学生账号。
# 详见 PLATFORM-INTEGRATION.md。
# ═══════════════════════════════════════════════════════════════

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
            "currentWeek": max((lesson.week or lesson.order for lesson in context.lessons), default=1),
            "lessons": [],
        })
        seen_lesson_ids = {item["lessonId"] for item in course["lessons"]}
        for lesson in context.lessons:
            if lesson.id in seen_lesson_ids:
                continue
            seen_lesson_ids.add(lesson.id)
            course["lessons"].append({
                "lessonId": lesson.id,
                "week": lesson.week or lesson.order,
                "lessonNumber": lesson.lesson_number,
                "teachingHours": lesson.teaching_hours,
                "chapter": f"第 {lesson.week or lesson.order} 周 · 第 {lesson.lesson_number or 1} 次课",
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
                    "chapter": f"第 {lesson.week or lesson.order} 周 · 第 {lesson.lesson_number or 1} 次课",
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
                    "classroomId": lesson.classroom.id if lesson.classroom else None,
                    "playerUrl": lesson.classroom.player_url if lesson.classroom else "",
                }
    raise HTTPException(status_code=404, detail="未找到该课时的学习上下文（请从平台进入）")


@app.get("/api/session/health")
def session_health() -> dict:
    """平台探活端点（student_bridge 的 studentAgentReady 检查）。

    frontendStale 为真 = /app 正在服务一份和 frontend/src 对不上的旧构建
    （不影响探活判定，只作诊断信号，见上方「旧构建守卫」）。
    """
    return {"ok": True, "frontendStale": bool(FRONTEND_STALE_REASON)}


# ═══════════════════════════════════════════════════════════════
# 前端（Next.js 学生端）
#
# 源码在 frontend/，构建产物同步到 apps/static/app/。
# 挂在跟 /api 同一个源下，浏览器不认为是跨域，所以**不需要 CORS**。
# ⚠️ next.config.mjs 里 basePath="/app"，所以必须挂在 /app 而不是 / ——
# 平台的 Caddy 也是把 /app* 转发到本服务。改成挂 "/" 会让资源全部 404。
# 构建：cd frontend && npm run build，再把 out/ 拷到 apps/static/app/
# ═══════════════════════════════════════════════════════════════

FRONTEND_DIR = STATIC_DIR / "app"
if not (FRONTEND_DIR / "index.html").is_file() and (FRONTEND_OUT_DIR / "index.html").is_file():
    # 还没跑同步那一步时，直接用 frontend/out 的产物（basePath 同样是 /app）
    FRONTEND_DIR = FRONTEND_OUT_DIR
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


# ── 旧构建守卫 ─────────────────────────────────────────────────
# 上面的目录是**上次构建**的产物：改了 frontend/src 忘记重新构建时，浏览器
# 拿到的是旧行为，而且全程零报错——症状还会指向别处（2026-10-09 的
# 「刷新后掉登录/加入课程门」排查就是栽在这，旧产物比源码旧了 12 天）。
# npm run build 会把源码指纹写进 out/.build-fingerprint
# （frontend/scripts/write-build-fingerprint.mjs），这里启动时重算比对。

FRONTEND_SRC_DIR = ROOT / "frontend" / "src"
FRONTEND_BUILD_INPUTS = ("package.json", "package-lock.json", "next.config.mjs")


def _frontend_fingerprint() -> str | None:
    """与 frontend/scripts/write-build-fingerprint.mjs 同一套算法，勿单边改。"""
    import hashlib

    if not FRONTEND_SRC_DIR.is_dir():
        return None  # 容器等场景可能只带产物没带源码，无从比对
    inputs: list[tuple[str, bytes]] = []
    for name in FRONTEND_BUILD_INPUTS:
        path = ROOT / "frontend" / name
        if path.is_file():
            inputs.append((name, path.read_bytes()))
    for path in FRONTEND_SRC_DIR.rglob("*"):
        if path.is_file():
            inputs.append((path.relative_to(ROOT / "frontend").as_posix(), path.read_bytes()))
    if not inputs:
        return None
    combined = hashlib.sha256()
    for rel, blob in sorted(inputs):
        combined.update(rel.encode("utf-8"))
        combined.update(b"\0")
        combined.update(hashlib.sha256(blob).digest())
    return combined.hexdigest()


def _frontend_stale_reason() -> str | None:
    if not (FRONTEND_DIR / "index.html").is_file():
        return None  # 一次都没构建过 —— /app 的 404 文案已经在教怎么做了
    expected = _frontend_fingerprint()
    if expected is None:
        return None
    try:
        actual = (FRONTEND_DIR / ".build-fingerprint").read_text(encoding="utf-8").strip()
    except OSError:
        return "构建产物里没有指纹文件（它早于指纹机制生成），无法证明与源码一致"
    if actual != expected:
        return "frontend/src 与上次构建的产物不一致（改了源码没有重新构建）"
    return None


FRONTEND_STALE_REASON = _frontend_stale_reason()
if FRONTEND_STALE_REASON:
    print(
        "\n" + "!" * 64
        + "\n!! 警告：" + FRONTEND_STALE_REASON
        + "\n!! 现在 /app 服务的是旧前端，页面行为不会反映你的改动。"
        + "\n!! 修复：在 student_agent/ 下运行 构建前端.cmd（或 cd frontend && npm run build"
        + " 后把 out/ 同步到 apps/static/app/）"
        + "\n" + "!" * 64 + "\n",
        flush=True,
    )


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


@app.get("/")
def index() -> HTMLResponse:
    """无平台令牌时显示入口提示，避免与前端的令牌检查形成重定向循环。"""
    return HTMLResponse(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>学生端入口</title><body style='font:16px system-ui;max-width:640px;"
        "margin:15vh auto;padding:24px;color:#172033'>"
        "<h1>请从课程平台进入</h1><p>学生端课堂需要平台签发的启动令牌。"
        "请先在课程平台选择已发布课程，再打开学生端。</p></body></html>",
        status_code=200,
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("AGENT_PORT", "8000")), log_level="info")
