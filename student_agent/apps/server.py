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
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

from agent import (  # noqa: E402
    EVENT_BEGIN, EVENT_MEDIA_DONE, EVENT_NEXT_STAGE,
    STAGE_NAMES, STAR_STATUS, build_graph, initial_state, is_uploaded_lesson,
    kp_title, lesson_source_label, list_lesson_ids, load_lesson,
    run_turn_stateless, safe_lesson_id, save_lesson, validate_plan,
)

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover
    raise SystemExit("缺依赖：pip install fastapi uvicorn")


TICK_SECONDS = float(os.environ.get("AGENT_TICK_SECONDS", "10"))
SESSIONS_DIR = ROOT / "runtime" / "sessions"
STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_OUT_DIR = ROOT / "frontend" / "out"

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


def _require_lesson(lesson_id: str) -> tuple[dict, list[dict]]:
    """取一份课时定义，非法 id 或找不到都 404。"""
    try:
        safe_lesson_id(lesson_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    lesson = load_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, f"课时不存在：{lesson_id}")
    return lesson


def _lesson_segments(plan: dict, segments: list[dict]) -> list[dict]:
    """把段落整理成前端要的形状。旧式课时的段落散在 segments/ 目录，
    新式的内联在同一个课时文件里 —— 两种都由 load_lesson 统一成第二参数。"""
    result = []
    elapsed = 0
    for index, item in enumerate(plan.get("segments") or []):
        segment_id = item.get("id")
        detail = next(
            (s for s in segments
             if s.get("id") == segment_id or s.get("segment_id") == segment_id),
            None,
        ) or {}
        minutes = float(item.get("minutes") or detail.get("minutes") or 0)
        start_seconds = round(elapsed * 60)
        elapsed += minutes
        result.append({
            "segmentId": segment_id,
            "title": detail.get("title") or segment_id,
            "order": detail.get("order") or index + 1,
            "startSeconds": start_seconds,
            "endSeconds": round(elapsed * 60),
            "knowledgePoints": detail.get("knowledge_points") or [],
        })
    return result


def _lesson_payload(lesson_id: str) -> dict:
    plan, raw_segments = _require_lesson(lesson_id)
    segments = _lesson_segments(plan, raw_segments)
    knowledge_points = []
    for segment in segments:
        for name in segment.get("knowledgePoints") or []:
            if name not in knowledge_points:
                knowledge_points.append(name)
    title = str(plan.get("lesson_title") or plan.get("lesson_id") or "本节课")
    display_title = title.split(" ", 1)[-1] if " " in title else title
    summary = plan.get("summary") or "；".join(segment["title"] for segment in segments[:3])
    return {
        "lessonId": plan.get("lesson_id"),
        "courseId": plan.get("course_id") or "operating-systems",
        "course": plan.get("course") or "操作系统",
        "chapter": plan.get("chapter") or "",
        # 课程级的三个字段跟着课时一起回，目录接口就不用为了分组再读一遍盘
        "week": int(plan.get("week") or 0),
        "courseIcon": plan.get("course_icon") or "▤",
        "courseSummary": plan.get("course_summary") or "",
        "title": display_title,
        "summary": summary or "按照课程计划完成引导学习、复述与深入探究。",
        "knowledgePointCount": len(knowledge_points),
        "segmentCount": len(segments),
        "estimatedMinutes": plan.get("total_minutes"),
        "knowledgePoints": knowledge_points,
        "segments": segments,
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
    student_id: str = "student-001"
    lesson_id: str = "ch3-process-scheduling"
    time_scale: float = 1.0        # >1 压缩时间：课前演练用 12 倍把 45 分钟压到 4 分钟
    launch_token: str | None = None  # 平台签发的可信启动令牌；提供时覆盖 student_id 并绑定课程上下文


class MessageIn(BaseModel):
    text: str


@app.get("/api/student/courses")
def student_courses(request: Request) -> dict:
    """课程目录。每门课带一个 `joined` 标记。

    目录本身是公开的（能看见有哪些课），**能上哪门由登录后的选课决定** ——
    前端据此把没加入的课渲染成"输课程码加入"。
    """
    student = _read_student(request.cookies.get(STUDENT_COOKIE, ""))
    mine = set(_joined_courses(student["studentId"])) if student else set()

    courses: dict[str, dict] = {}
    for lesson_id in list_lesson_ids():
        try:
            lesson = _lesson_payload(lesson_id)
        except HTTPException:
            continue                      # 单节课坏了不该拖垮整个目录
        entry = courses.setdefault(lesson["courseId"], {
            "courseId": lesson["courseId"],
            "name": lesson["course"],
            "summary": lesson["courseSummary"],
            "icon": lesson["courseIcon"],
            "joined": lesson["courseId"] in mine,
            "currentWeek": 0,
            "lessons": [],
        })
        entry["currentWeek"] = max(entry["currentWeek"], lesson["week"])
        entry["lessons"].append({
            "lessonId": lesson["lessonId"],
            "week": lesson["week"],
            "chapter": lesson["chapter"],
            "title": lesson["title"],
            "summary": lesson["summary"],
            "status": "current",
            "estimatedMinutes": lesson["estimatedMinutes"],
            "knowledgePoints": lesson["knowledgePoints"],
        })
    return {"ok": True, "courses": list(courses.values())}


@app.get("/api/lesson")
def lesson(lessonId: str) -> dict:
    return {"ok": True, "lesson": _lesson_payload(lessonId)}


@app.get("/api/lesson/video")
def lesson_video(lessonId: str) -> dict:
    payload = _lesson_payload(lessonId)
    url = os.environ.get("LESSON_VIDEO_URL", "").strip()
    video = None
    if url:
        video = {
            "url": url,
            "poster": os.environ.get("LESSON_VIDEO_POSTER", "").strip(),
            "duration": int(payload["estimatedMinutes"] or 0) * 60,
            "title": f"{payload['title']} · 教学视频",
            "source": "published",
        }
    return {"ok": True, "video": video}


# ═══════════════════════════════════════════════════════════════
# 老师侧：上传课时定义
#
# 解决的问题：以前老师要让 AI 知道"这节课讲什么"，只能手工去改
# rules/KNOWLEDGE-BASE.md、lesson-data/lesson-plan.json、
# lesson-data/segments/*.json 三处文件；而编排器的 load_context 虽然
# 会把这些装配进 assembled_prompt，那个字段却从没被送进模型。
# 现在：写一个接口收课时定义，落盘成 lesson-data/lessons/<id>.json，
# 由 agent 的 load_context 每轮读进 [本课知识点] 区块，
# 再由 llm_polish 随 assembled_prompt 一起交给模型。
# ═══════════════════════════════════════════════════════════════

class KnowledgePointIn(BaseModel):
    """一个知识点。字段名与 rules/KNOWLEDGE-BASE.md 一致，
    老师从知识库里复制过来就能直接提交。"""
    kp_id: str
    title: str
    定义: str = ""
    检测问题: str = ""
    掌握表现: str = ""
    为什么这样设计: str = ""
    如何实现: str = ""
    解决什么实际问题: str = ""
    关联学科: str = ""


class SegmentIn(BaseModel):
    id: str
    minutes: float
    title: str = ""
    order: int | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    knowledge_points: list[str] = Field(default_factory=list)
    summary: str = ""
    content: str = ""
    source: dict = Field(default_factory=dict)


class StageIn(BaseModel):
    """一个教学阶段。用模型接而不是 list[dict]：minutes 写成字符串时
    pydantic 会转成数字，而裸 dict 会一路走到 validate_plan 的 sum() 里
    炸成 500 —— 接口该回 422，不该 500。"""
    id: str
    enabled: bool = False
    minutes: float = 0
    advance_when: str = "either"
    delivery: str | None = None


class LessonIn(BaseModel):
    lesson_id: str
    lesson_title: str
    total_minutes: float
    stages: list[StageIn] = Field(default_factory=list)
    segments: list[SegmentIn] = Field(default_factory=list)
    knowledge_points: list[KnowledgePointIn] = Field(default_factory=list)
    advance_policy: dict | None = None
    course_id: str = "operating-systems"
    course: str = "操作系统"
    chapter: str = ""
    week: int = 0
    summary: str = ""
    course_icon: str = ""
    course_summary: str = ""


DEFAULT_ADVANCE_POLICY = {
    "on_budget_exhausted": "wrap_up",
    "on_evidence_reached": "advance",
    "min_stage_minutes": 2,
    "max_stage_overrun_minutes": 3,
}


@app.post("/api/teacher/lesson")
def teacher_upsert_lesson(body: LessonIn) -> dict:
    """老师上传 / 覆盖一份课时定义。

    校验用的就是开课时那一套 validate_plan —— 这里过了，开课就不会再因为
    计划本身失败。写入是"先写临时文件再原子替换"，避免读端拿到写了一半的 JSON。
    """
    try:
        lesson_id = safe_lesson_id(body.lesson_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    segments = [seg.model_dump() for seg in body.segments]
    for index, seg in enumerate(segments):
        seg.setdefault("segment_id", seg["id"])
        if not seg.get("order"):
            seg["order"] = index + 1

    doc = {
        "lesson_id": lesson_id,
        "lesson_title": body.lesson_title,
        "course_id": body.course_id,
        "course": body.course,
        "chapter": body.chapter,
        "week": body.week,
        "summary": body.summary,
        "course_icon": body.course_icon,
        "course_summary": body.course_summary,
        "total_minutes": body.total_minutes,
        # exclude_none：没写 delivery 的阶段不该落一个 "delivery": null 进文件
        "stages": [s.model_dump(exclude_none=True) for s in body.stages],
        "segments": segments,
        "knowledge_points": [kp.model_dump() for kp in body.knowledge_points],
        "advance_policy": body.advance_policy or dict(DEFAULT_ADVANCE_POLICY),
    }

    problems = validate_plan(doc, uploaded=True)
    if problems:
        raise HTTPException(
            422, detail="课时定义校验失败：\n- " + "\n- ".join(problems)
        )

    path_label = save_lesson(doc)

    # 已经在跑的会话缓存了旧的 lesson_plan（load_plan 幂等），改了也读不到。
    # 遍历注册表要持锁 —— 心跳线程会并发增删条目，裸迭代可能抛
    # "dictionary changed size during iteration"。
    with _REGISTRY_LOCK:
        running = [
            sid for sid, s in SESSIONS.items()
            if s["state"].get("lesson_id") == lesson_id
            and s["state"].get("lesson_status") == "running"
        ]
    return {
        "ok": True,
        "lesson_id": lesson_id,
        "path": path_label,
        "knowledgePointCount": len(doc["knowledge_points"]),
        "segmentCount": len(segments),
        "staleSessions": running,
        "note": (
            f"{len(running)} 个正在上课的会话仍在用旧版本，要等它们结束或新建会话才会读到本次改动。"
            if running else ""
        ),
    }


@app.get("/api/teacher/lesson/{lesson_id}")
def teacher_get_lesson(lesson_id: str) -> dict:
    """回读一份课时定义，确认存进去的是什么（含校验结果）。"""
    try:
        safe_lesson_id(lesson_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    doc, _ = _require_lesson(lesson_id)
    return {
        "ok": True,
        "lesson": doc,
        "source": lesson_source_label(lesson_id),
        "problems": validate_plan(doc, uploaded=is_uploaded_lesson(lesson_id)),
    }
# ═══════════════════════════════════════════════════════════════
# 学生账户：自注册 + 用课程码加入
#
# 背景：本仓库原本没有任何身份概念 —— 前端 api.js 把 student_id 写死成
# "student-001"。这一块补上：学生自己注册（学号 + 姓名 + 密码），
# 拿老师给的课程码加入课程，之后只看得见自己加入的课。
#
# 存储（都在 runtime/ 下，已进 .gitignore）：
#   runtime/accounts.json                       账户表（密码 PBKDF2 哈希，不存明文）
#   runtime/students/<studentId>/courses.json   该学生的选课
#   lesson-data/join-codes.json                 课程码（老师侧生成，随仓库走）
#
# ⚠️ 边界（别高估它）：
#   · 密码是 PBKDF2-HMAC-SHA256（20 万轮）+ 每账户独立 salt，服务端校验；
#     cookie 是 HMAC 签名的，改一个字节即失效。
#   · **业务端点尚未强制校验 cookie** —— 这层拦得住界面，拦不住 curl。
#     要真正封住接口需要再加一个 FastAPI 依赖挂到 /api/student/* 与
#     /api/session/* 上，见 apps/API-SAAS.md §5。
#   · 没做：token 过期（cookie 有 max_age，token 本身不过期）、
#     登出黑名单、找回密码、并发登录限制。
# ═══════════════════════════════════════════════════════════════

ACCOUNTS_PATH = ROOT / "runtime" / "accounts.json"
JOIN_CODES_PATH = ROOT / "lesson-data" / "join-codes.json"
STUDENT_COOKIE = "student_session"

# 签名密钥。设了 AGENT_SESSION_SECRET 就用它（重启后已发的 cookie 仍有效）；
# 没设就每次启动随机生成一个（重启即全员掉线，本地开发够用）。
SESSION_SECRET = os.environ.get("AGENT_SESSION_SECRET") or secrets.token_hex(32)
PBKDF2_ROUNDS = 200_000

_ACCOUNTS_LOCK = threading.Lock()


class StudentRegisterIn(BaseModel):
    student_number: str
    name: str
    password: str


class StudentLoginIn(BaseModel):
    student_number: str
    password: str


class StudentJoinIn(BaseModel):
    code: str


class CourseCodeIn(BaseModel):
    course_id: str
    regenerate: bool = False


def _read_json_file(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_file(path: Path, data) -> None:
    """先写临时文件再原子替换 —— 半截 JSON 会让所有人登不进来。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── 账户 ──────────────────────────────────────────────────────

def _accounts() -> dict[str, dict]:
    """学号 → 账户记录。"""
    data = _read_json_file(ACCOUNTS_PATH, {})
    return data.get("accounts", {}) if isinstance(data, dict) else {}


def _save_accounts(accounts: dict[str, dict]) -> None:
    _write_json_file(ACCOUNTS_PATH, {"accounts": accounts})


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS
    ).hex()


def _student_id_for(number: str) -> str:
    """学号 → 稳定的 studentId。

    它会用作 runtime/students/<id>/ 的目录名，所以只留安全字符；
    全被过滤掉时退回学号的哈希（保证稳定且不撞车）。
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "", number)
    if safe and safe[0].isalnum():
        return f"stu-{safe}"
    return "stu-" + hashlib.sha256(number.encode("utf-8")).hexdigest()[:12]


def _account_dir(student_id: str) -> Path:
    """与大仓 agent._student_dir 同一套清洗规则。"""
    safe = re.sub(r"[^\w\-.]", "_", student_id) or "unknown"
    return ROOT / "runtime" / "students" / safe


def _public_student(record: dict | None) -> dict | None:
    """只回前端需要的字段 —— salt/hash 绝不能出门。"""
    if not record:
        return None
    return {
        "studentId": record.get("studentId"),
        "name": record.get("name"),
        "studentNumber": record.get("studentNumber"),
    }


def _sign_student(student_id: str) -> str:
    mac = hmac.new(
        SESSION_SECRET.encode(), student_id.encode(), hashlib.sha256
    ).hexdigest()
    return f"{student_id}.{mac}"


def _token_student_id(token: str) -> str | None:
    """只验签名，不查账户 —— 账户可能已被删。"""
    if not token or "." not in token:
        return None
    student_id, _, mac = token.rpartition(".")
    expected = hmac.new(
        SESSION_SECRET.encode(), student_id.encode(), hashlib.sha256
    ).hexdigest()
    return student_id if hmac.compare_digest(mac, expected) else None


def _read_student(token: str) -> dict | None:
    """验签名 + 确认账户还在。"""
    student_id = _token_student_id(token)
    if not student_id:
        return None
    return next(
        (r for r in _accounts().values() if r.get("studentId") == student_id), None
    )


def _set_session_cookie(response: Response, student_id: str) -> None:
    response.set_cookie(
        STUDENT_COOKIE,
        _sign_student(student_id),
        httponly=True,
        # 跨域/跨站 iframe 部署需 AGENT_COOKIE_SAMESITE=none（此时浏览器还要求
        # Secure，即同时设 AGENT_COOKIE_SECURE=1），否则登录态 Cookie 不会随请求带上。
        samesite=os.environ.get("AGENT_COOKIE_SAMESITE", "lax"),
        path="/",
        max_age=60 * 60 * 12,
        secure=os.environ.get("AGENT_COOKIE_SECURE") == "1",
    )


# ── 选课 ──────────────────────────────────────────────────────

def _joined_courses(student_id: str) -> list[str]:
    data = _read_json_file(_account_dir(student_id) / "courses.json", {})
    courses = data.get("courses") if isinstance(data, dict) else None
    if not isinstance(courses, list):
        return []
    return [c for c in courses if isinstance(c, str)]


def _join_course(student_id: str, course_id: str) -> list[str]:
    courses = _joined_courses(student_id)
    if course_id not in courses:
        courses.append(course_id)
        _write_json_file(
            _account_dir(student_id) / "courses.json", {"courses": courses}
        )
    return courses


def _join_codes() -> dict[str, str]:
    data = _read_json_file(JOIN_CODES_PATH, {})
    return data.get("codes", {}) if isinstance(data, dict) else {}


def _course_for_code(code: str) -> str | None:
    """课程码 → course_id。大小写不敏感，忽略两头空格。"""
    wanted = code.strip().upper()
    if not wanted:
        return None
    return next((cid for cid, c in _join_codes().items() if c.upper() == wanted), None)


def _known_course_ids() -> list[str]:
    """本系统里出现过的 course_id（从课时定义推导，没有独立的课程表）。"""
    ids: list[str] = []
    for lesson_id in list_lesson_ids():
        try:
            course_id = _lesson_payload(lesson_id)["courseId"]
        except HTTPException:
            continue
        if course_id and course_id not in ids:
            ids.append(course_id)
    return ids


# ── 接口 ──────────────────────────────────────────────────────

@app.get("/api/student/session")
def student_session(request: Request) -> dict:
    """当前登录状态 + 已加入的课程。前端靠它决定显示登录页还是课堂。"""
    student = _read_student(request.cookies.get(STUDENT_COOKIE, ""))
    return {
        "ok": True,
        "authenticated": student is not None,
        "student": _public_student(student),
        "courses": _joined_courses(student["studentId"]) if student else [],
    }


@app.post("/api/student/register")
def student_register(body: StudentRegisterIn, response: Response) -> dict:
    """自注册。学号即账号，注册完直接登录。"""
    number = body.student_number.strip()
    name = body.name.strip()
    if not number or not name:
        raise HTTPException(400, "学号和姓名都不能为空")
    if len(body.password) < 6:
        raise HTTPException(400, "密码至少 6 位")

    with _ACCOUNTS_LOCK:
        accounts = _accounts()
        if number in accounts:
            raise HTTPException(409, "该学号已注册，直接登录即可")
        salt = secrets.token_hex(16)
        accounts[number] = {
            "studentNumber": number,
            "studentId": _student_id_for(number),
            "name": name,
            "salt": salt,
            "hash": _hash_password(body.password, salt),
            "createdAt": _now(),
        }
        _save_accounts(accounts)
        record = accounts[number]

    _set_session_cookie(response, record["studentId"])
    return {"ok": True, "student": _public_student(record), "courses": []}


@app.post("/api/student/login")
def student_login(body: StudentLoginIn, response: Response) -> dict:
    number = body.student_number.strip()
    with _ACCOUNTS_LOCK:
        record = _accounts().get(number)
    # 学号不存在和密码错回同一句 —— 别让人拿这个接口枚举注册过的学号
    if not record:
        raise HTTPException(401, "学号或密码不正确")
    actual = _hash_password(body.password, str(record.get("salt") or ""))
    if not hmac.compare_digest(actual, str(record.get("hash") or "")):
        raise HTTPException(401, "学号或密码不正确")

    _set_session_cookie(response, record["studentId"])
    return {
        "ok": True,
        "student": _public_student(record),
        "courses": _joined_courses(record["studentId"]),
    }


@app.post("/api/student/logout")
def student_logout(response: Response) -> dict:
    response.delete_cookie(STUDENT_COOKIE, path="/")
    return {"ok": True}


@app.post("/api/student/join")
def student_join(body: StudentJoinIn, request: Request) -> dict:
    """用老师给的课程码加入课程。"""
    student = _read_student(request.cookies.get(STUDENT_COOKIE, ""))
    if not student:
        raise HTTPException(401, "请先登录再加入课程")

    course_id = _course_for_code(body.code)
    if not course_id:
        raise HTTPException(404, "课程码无效，找老师确认一下")

    return {
        "ok": True,
        "courseId": course_id,
        "courses": _join_course(student["studentId"], course_id),
    }


@app.post("/api/teacher/course-code")
def teacher_course_code(body: CourseCodeIn) -> dict:
    """生成（或取回）某门课的加入码。regenerate=true 会换一个新码。"""
    if body.course_id not in _known_course_ids():
        raise HTTPException(404, f"课程不存在：{body.course_id}")

    codes = _join_codes()
    if body.regenerate or body.course_id not in codes:
        # 去掉容易看错的 0/O/1/I
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        codes[body.course_id] = "".join(secrets.choice(alphabet) for _ in range(6))
        _write_json_file(JOIN_CODES_PATH, {"codes": codes})

    return {"ok": True, "courseId": body.course_id, "code": codes[body.course_id]}


@app.get("/api/teacher/course-code/{course_id}")
def teacher_get_course_code(course_id: str) -> dict:
    code = _join_codes().get(course_id)
    if not code:
        raise HTTPException(404, f"{course_id} 还没有课程码，先 POST 生成一个")
    return {"ok": True, "courseId": course_id, "code": code}


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

    # 先校验再动注册表，非法 id 不该留下任何痕迹（_path 里还有一道兜底）
    sid = _safe_sid(body.session_id) if body.session_id else f"cls-{uuid.uuid4().hex[:8]}"
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


@app.post("/api/session/{sid}/begin")
def begin(sid: str) -> dict:
    """★ 课堂开始。老师按「开始上课」按钮时调这个。

    这一轮会加载课程计划、说开场白、切进第一个环节并开始计时。
    """
    st = _begin_lesson(sid)
    _record_learning_event(sid, event_type="lesson_began")
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
        "ok": True,
        "reply_text": st.get("reply_text", ""),
        "phase": st.get("host_phase"),
        "phase_name": STAGE_NAMES.get(st.get("host_phase"), st.get("host_phase")),
        "status": st.get("lesson_status"),
        "current_question": st.get("current_question"),
        "stars": st.get("kp_stars") or {},
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
                    {"kp_id": kp, "title": kp_title(kp, lesson_id), "stars": v,
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


@app.get("/api/session/demo-flag")
def demo_flag() -> dict:
    """前端探测后端是否处于显式 demo 模式（仅此时允许加载内置演示课）。"""
    from apps.integration import config as integration_config
    return {"demoMode": integration_config.demo_mode()}


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
def index() -> FileResponse:
    """独立态首页（旧版单页）。平台入口走 /app。"""
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("AGENT_PORT", "8000")), log_level="info")
