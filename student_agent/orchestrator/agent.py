"""主动引导智能体 —— 真实 LangGraph 编排器实现。

依据 `orchestrator/ORCHESTRATOR.md` 规范实现，覆盖全部 11 个节点：
load_plan / tick / load_context / classify_turn / host_event / teach /
judge_mastery / judge_advance / advance_stage / write_state / format_reply

关键约定（与规范一致）：
- `now` 由会话层注入 state，图内任何节点不调 datetime.now() → 可单测、可回放。
- 判断写进 state（target_phase），路由函数只读不判。
- `stage_snapshots` 用 Annotated[list, operator.add] 累加，不覆盖。
- 空壳降级：stages/*/questions.md 为空 → TMISSION 检验问题 → KNOWLEDGE-BASE 检测问题。

LLM 接入（可选）：
    设置环境变量 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY / AGENT_LLM_MODEL
    （任意 OpenAI 兼容 /chat/completions 端点）后，teach 节点改用真实大模型。
    未配置时 teach 走规范第 8 节的确定性降级行为，整张图照样能跑完整节课。
    星级判定（judge_mastery）始终是确定性的关键词匹配，不依赖模型。

运行演示：python orchestrator/run_demo.py
"""

from __future__ import annotations

import json
import operator
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """读仓库根的 .env.local（若存在），写入 os.environ。

    只在变量尚未设置时写入，保证命令行传入的环境变量优先级更高。
    文件本身已进 .gitignore，不会把 API Key 提交进版本库。
    """
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_dotenv()

STAGE_NAMES = {
    "guided_learning": "讲解阶段",
    "recap_discussion": "复述阶段",
    "deep_inquiry": "深层探究阶段",
    "class_discussion": "全班讨论阶段",
}
STAR_STATUS = {1: "已接触", 2: "初步理解", 3: "理解中", 4: "接近掌握"}

# 外部事件取值（会话层注入 `external_event`）
EVENT_BEGIN = "begin"            # 课堂开始
EVENT_MEDIA_DONE = "media_done"  # 一段视频/素材播放完成
EVENT_NEXT_STAGE = "next_stage"  # 老师按"下一环节"，强制切幕


def stage_delivery(state: ClassroomState) -> str:
    """讲解阶段（guided_learning）的授课方式，来自 lesson-plan.json：

    - ``video``：**一整段视频替代讲解**。AI 全程静默不出讲解词，
      视频播放的时间照常计入课堂时间；切幕只由「视频播完」（media_done）
      或老师按钮驱动，**时间预算不切**——视频多长都等它放完。
    - ``narration``（默认）：AI 逐段讲解（无视频的课用这种方式）。
    """
    for s in (state.get("lesson_plan") or {}).get("stages", []):
        if s.get("id") == "guided_learning":
            return s.get("delivery") or "narration"
    return "narration"

# 切幕开场白里告诉学生"这一环节要干什么"。
# 注意：**不要在这里写时间预算**——模型会照着念，学生没必要知道幕后的分钟数。
STAGE_GOAL = {
    "guided_learning": "我会把本课的新内容带你过一遍",
    "recap_discussion": "这一环节请你用自己的话把刚才的内容讲一遍",
    "deep_inquiry": "我们往深处挖一挖：为什么会这样设计、具体怎么实现、能用在哪儿",
    "class_discussion": "这一环节请老师来主导讨论，我在旁边协助",
}


# ═══════════════════════════════════════════════════════════════
# LLM 可插拔层（OpenAI 兼容端点；未配置返回 None → 走确定性脚本）
# ═══════════════════════════════════════════════════════════════

def llm_available() -> bool:
    return bool(
        os.environ.get("AGENT_LLM_BASE_URL")
        and os.environ.get("AGENT_LLM_API_KEY")
        and os.environ.get("AGENT_LLM_MODEL")
    )


# 诊断计数：实测时用，能立刻看出"到底调没调成功"
LLM_DIAG: dict = {"calls": 0, "ok": 0, "failed": 0, "last_error": None}


def llm_chat(system: str, user: str) -> str | None:
    """调 OpenAI 兼容端点。失败时**不静默**——写诊断并打日志。

    返回 None 时调用方走确定性降级脚本，但 last_error 会保留原因，
    否则实测时分不清"没接上"和"接上了但走了兜底"。
    """
    base = os.environ.get("AGENT_LLM_BASE_URL")
    key = os.environ.get("AGENT_LLM_API_KEY")
    model = os.environ.get("AGENT_LLM_MODEL")
    if not (base and key and model):
        return None
    LLM_DIAG["calls"] += 1
    try:
        payload = json.dumps(
            {"model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]},
        ).encode("utf-8")
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        LLM_DIAG["ok"] += 1
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        LLM_DIAG["failed"] += 1
        LLM_DIAG["last_error"] = f"{type(e).__name__}: {e}"
        print(f"[LLM 调用失败] {type(e).__name__}: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
# 证据匹配 —— 星级判定的确定性核心（judge_mastery 与 teach 共用）
# 每个 KP 分若干"证据组"，学生话语命中全部组 = 完整证据，命中部分 = 零散要点。
# 关键词取自 runtime/TMISSION.md 的 答对证据。
# ═══════════════════════════════════════════════════════════════

_KP_TITLES: dict[str, str] | None = None


def kp_title(kp_id: str) -> str:
    """KP 编号 → 中文标题（取自 `## KP-001 调度是什么` 这一行）。

    模型生成的回复要用标题，**不能把 KP-004 这类内部编号说给学生听**。
    取不到时原样返回编号（宁可说编号，也不要编标题）。
    """
    global _KP_TITLES
    if _KP_TITLES is None:
        _KP_TITLES = {}
        text = _read("rules/KNOWLEDGE-BASE.md")
        for m in re.finditer(r"^##\s+(KP-\d+)\s+(.+)$", text or "", re.M):
            _KP_TITLES[m.group(1)] = m.group(2).strip()
    return _KP_TITLES.get(kp_id, kp_id)


EVIDENCE_GROUPS: dict[str, list[list[str]]] = {
    "KP-001": [["CPU", "一个进程", "只能"], ["调度", "规则", "谁先"]],
    "KP-002": [
        ["高级调度", "作业调度", "调入内存", "作业调入"],
        ["低级调度", "进程调度", "就绪", "上 CPU", "上CPU"],
        ["中级调度", "对换", "内存平衡"],
    ],
    "KP-003": [
        ["周转", "提交", "完成"],
        ["等待时间", "就绪队列"],
        ["响应时间", "首次", "第一次"],
    ],
    "KP-004": [
        ["饥饿", "长作业", "等很久"],
        ["HRRN", "响应比", "动态优先级", "等待时间加"],
    ],
    "KP-005": [
        ["打断", "中断", "抢占"],
        ["时间片", "优先级", "更短", "耗尽"],
    ],
    "KP-006": [
        ["时间片", "轮转", "RR"],
        ["多级反馈队列", "队列间", "移动"],
    ],
}


def match_evidence(kp_id: str, text: str, state: "ClassroomState | None" = None) -> tuple[int, int]:
    """返回 (命中的证据组数, 总组数)。

    平台正式链路：优先使用会话绑定的已发布评估契约（expected_concepts
    每个概念一组证据）；仅 demo 课回退本地 EVIDENCE_GROUPS。
    """
    if state is not None:
        plan = state.get("lesson_plan") or {}
        if plan.get("source") == "platform-published":
            for kp in plan.get("knowledge_points", []):
                if kp["id"] != kp_id:
                    continue
                concepts = kp.get("expected") or []
                if not concepts:
                    return (1, 1) if text.strip() else (0, 1)
                hits = sum(1 for c in concepts if c and c in text)
                return (hits, len(concepts))
            return (0, 0)
    groups = EVIDENCE_GROUPS.get(kp_id, [])
    if not groups:
        return (0, 0)
    hits = sum(1 for g in groups if any(kw in text for kw in g))
    return (hits, len(groups))


# ═══════════════════════════════════════════════════════════════
# 三级问题兜底链：
#   stages/<phase>/questions.md → runtime/TMISSION.md 检验问题 → KNOWLEDGE-BASE 检测问题
# ═══════════════════════════════════════════════════════════════

def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _parse_stage_questions(phase: str) -> list[dict]:
    """第 1 级：stages/<phase>/questions.md 里老师填的问题（剥掉代码块示例）。"""
    text = _read(f"stages/{phase}/questions.md")
    if not text:
        return []
    body = _strip_code_fences(text)
    out: list[dict] = []
    for block in re.split(r"^## 问题", body, flags=re.M)[1:]:
        m_kp = re.search(r"关联[:：]\s*(KP-\d+|seg-\d+)", block)
        m_q = re.search(r"问题[:：]\s*(.+)", block)
        if m_kp and m_q:
            out.append({
                "kp_id": m_kp.group(1),
                "question": m_q.group(1).strip(),
                "source": "stages/questions.md",
            })
    return out


def _parse_tmission_questions() -> list[dict]:
    """第 2 级：runtime/TMISSION.md 核心难点的 检验问题。"""
    text = _read("runtime/TMISSION.md")
    if not text:
        return []
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"-\s+(KP-\d+)\s", line)
        if m:
            cur = m.group(1)
            continue
        m2 = re.match(r"\s*-\s*检验问题[:：]\s*(.+)", line)
        if m2 and cur:
            out.append({
                "kp_id": cur,
                "question": m2.group(1).strip(),
                "source": "runtime/TMISSION.md 检验问题",
            })
            cur = None
    return out


def _parse_kb_questions() -> list[dict]:
    """第 3 级：rules/KNOWLEDGE-BASE.md 各 KP 的 检测问题。"""
    text = _read("rules/KNOWLEDGE-BASE.md")
    if not text:
        return []
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"##\s+(KP-\d+)\s", line)
        if m:
            cur = m.group(1)
            continue
        m2 = re.match(r"-\s*检测问题[:：]\s*(.+)", line)
        if m2 and cur:
            out.append({
                "kp_id": cur,
                "question": m2.group(1).strip(),
                "source": "rules/KNOWLEDGE-BASE.md 检测问题",
            })
    return out


def build_question_queue(phase: str, unresolved: list[str], plan: dict | None = None) -> list[dict]:
    """按三级兜底链为复述/探究阶段组装问题队列。"""
    from apps.integration import prompt_context

    platform_questions = prompt_context.question_queue(phase, plan or {}, unresolved)
    if platform_questions:
        return platform_questions
    if phase == "recap_discussion":
        q = _parse_stage_questions("recap_discussion")
        if q:
            return q
        q = _parse_tmission_questions()
        if q:
            return q
        return _parse_kb_questions()

    if phase == "deep_inquiry":
        q = _parse_stage_questions("deep_inquiry")
        if q:
            return q
        # 探究字段（为什么/如何/用在哪）为空 → 降级为通用探究问题。
        # 未关闭的难点优先问，其余按已获星级排序。
        text = _read("rules/KNOWLEDGE-BASE.md")
        filled = re.search(r"为什么这样设计[:：]\s*\S", text or "")
        if filled:
            out = []
            for m in re.finditer(
                r"##\s+(KP-\d+)[^\n]*\n((?:-[^\n]*\n)+)", text
            ):
                kp, body = m.group(1), m.group(2)
                for field, lead in (
                    ("为什么这样设计", "为什么"),
                    ("如何实现", "如何"),
                    ("解决什么实际问题", "用在哪"),
                ):
                    fm = re.search(rf"-\s*{field}[:：]\s*(\S.*)", body)
                    if fm:
                        out.append({
                            "kp_id": kp,
                            "question": fm.group(1).strip(),
                            "source": "rules/KNOWLEDGE-BASE.md 探究字段",
                        })
            if out:
                return out
        # 全空 → 规范第 8 节兜底："这个知识点能解决什么实际问题"
        kps = list(dict.fromkeys(
            unresolved
            + [k for k in EVIDENCE_GROUPS if k not in unresolved]
        ))
        return [{
            "kp_id": kp,
            "question": (
                f"这个知识点（{kp_title(kp)}）能解决什么实际问题？"
                "结合一个具体场景，说说为什么需要它、它是怎么起作用的。"
            ),
            "source": "内置默认探究问题（探究字段为空的降级）",
        } for kp in kps[:4]]

    return []


# ═══════════════════════════════════════════════════════════════
# State —— 规范第 2 节 + 实现所需的运行字段
# ═══════════════════════════════════════════════════════════════

class ClassroomState(TypedDict):
    # ── 会话标识 ──
    session_id: str
    student_id: str
    lesson_id: str

    # ── 平台上下文（LangGraph 按键过滤，必须声明才能在图节点间传递）──
    platform: dict
    learning_context: dict

    # ── 编排器核心 ──
    host_phase: Literal[
        "uninitialized", "intro", "guided_learning",
        "recap_discussion", "deep_inquiry", "class_discussion", "ending",
    ]
    active_segment_id: str | None
    stage_started_at: str
    stage_elapsed_minutes: float
    lesson_elapsed_minutes: float
    stage_budget_minutes: float
    remaining_stages: list[str]
    advance_when: str
    now: str
    lesson_started_at: str | None

    # ── 会话层注入的运行参数 ──
    tick_only: bool                # True = 本轮只是心跳，没有学生输入
    time_scale: float              # 时间倍速，>1 用于课前把 45 分钟压缩成几分钟演练
    lesson_status: Literal["idle", "running", "ended"]
    # idle = 会话已建、老师还没点"开始上课"：这段时间**不计课时**，心跳也不会推 Wesley
    external_event: str | None
    # 本轮由外部（老师按钮 / 前端播放器）注入的事件，取值见 EVENT_*：
    #   begin        —— 课堂开始，等价于"起课铃"
    #   media_done   —— 一段讲解视频/素材播放完成
    #   next_stage   —— 老师按"下一环节"，无条件切幕
    # 每轮由会话层显式传值覆盖（None = 本轮无事件），不清空的话会渗进下一轮判定。
    segment_cursor: int            # 讲解阶段段落游标：时间到 +1，视频播完也 +1
    played_media: list[dict]       # 已播完的素材 [{"segment_id", "at"}]，给学情导出用

    # ── 推进策略（lesson-plan.json 的 advance_policy）──
    on_budget_exhausted: str
    on_evidence_reached: str
    min_stage_minutes: float
    max_stage_overrun_minutes: float

    # ── 教学状态 ──
    current_target: str | None
    current_question: str | None
    pending_question: dict | None     # 当前等待学生回答的问题 {kp_id, question, source}
    question_queue: list[dict]        # 本阶段的问题队列（三级兜底链产出）
    q_index: int
    attempts: int
    mastered: list[str]
    unresolved: list[str]

    # ── 学生 ──
    student_message: str
    speaker: Literal["host", "student"]
    student_status: Literal["active", "practicing", "waiting", "ended"]

    # ── 证据与掌握 ──
    turn_evidence: list[str]
    mastery_updates: list[dict]
    kp_stars: dict[str, int]          # 运行中的星级（落盘到 mastery-state.json）
    kp_meta: dict[str, dict]          # 各 KP 的 last_source/stage/evidence
    stage_snapshots: Annotated[list[dict], operator.add]

    # ── 输出 ──
    reply_text: str
    speech_kind: Literal["none", "auto"]
    advance_reason: str | None
    target_phase: str | None
    assembled_prompt: str
    lesson_plan: dict
    llm_used: bool                    # 本轮回复是否由大模型生成（实测时区分"接上/降级"）


# ═══════════════════════════════════════════════════════════════
# 节点实现
# ═══════════════════════════════════════════════════════════════

def load_plan(state: ClassroomState) -> dict:
    """载入并校验课程计划（规范第 9 节校验清单）。仅首轮生效，之后幂等。

    会话携带 learning_context（平台正式链路）时，课程计划由 course_adapter
    从已发布知识包/课堂动态生成；仅 demo 模式读取本地 lesson-plan.json。
    """
    if state.get("host_phase") != "uninitialized":
        return {}

    from apps.integration import course_adapter as _course_adapter

    plan = _course_adapter.load_plan_for_session(state)
    if plan is None:
        plan = json.loads((ROOT / "lesson-data/lesson-plan.json").read_text(encoding="utf-8"))

    # 启动校验（任一失败 → 拒绝开课）
    problems = _validate_plan(plan)
    if problems:
        return {
            "host_phase": "ending",
            "reply_text": "开课校验失败：\n- " + "\n- ".join(problems),
            "advance_reason": "开课校验失败",
        }

    enabled = [s for s in plan["stages"] if s.get("enabled")]
    policy = plan["advance_policy"]

    # 星级基线：读**该学生自己的**档案（runtime/students/<id>/mastery-state.json）。
    # 不读共享文件——那会让上一个学生的星级渗进下一个学生的新会话。
    # 同一学生跨课次则正常延续（学期内掌握度连续，这是设计意图）。
    kp_stars: dict[str, int] = {}
    try:
        ms = json.loads(
            (_student_dir(state) / "mastery-state.json").read_text(encoding="utf-8")
        )
        for kp, rec in (ms.get("knowledge_points") or {}).items():
            kp_stars[kp] = int(rec.get("stars", 0))
    except Exception:
        pass

    return {
        "lesson_plan": plan,
        "host_phase": "intro",
        "remaining_stages": [s["id"] for s in enabled],
        "stage_budget_minutes": 0.0,
        "advance_when": "budget",
        "lesson_started_at": state["now"],
        "stage_started_at": state["now"],
        "on_budget_exhausted": policy["on_budget_exhausted"],
        "on_evidence_reached": policy["on_evidence_reached"],
        "min_stage_minutes": float(policy["min_stage_minutes"]),
        "max_stage_overrun_minutes": float(policy["max_stage_overrun_minutes"]),
        "kp_stars": kp_stars,
        "kp_meta": {},
        "mastered": [],
        "unresolved": [],
        "question_queue": [],
        "q_index": 0,
        "attempts": 0,
    }


def _validate_plan(plan: dict) -> list[str]:
    problems: list[str] = []
    if plan.get("total_minutes", 0) <= 0:
        problems.append("total_minutes 必须大于 0")
    enabled = [s for s in plan.get("stages", []) if s.get("enabled")]
    if sum(s.get("minutes", 0) for s in enabled) > plan.get("total_minutes", 0):
        problems.append("启用阶段的时长之和超过 total_minutes")
    for s in enabled:
        if s.get("advance_when") not in ("either", "evidence", "budget"):
            problems.append(f"阶段 {s['id']} 的 advance_when 非法")
        if plan.get("source") != "platform-published" and s["id"] in ("recap_discussion", "deep_inquiry", "class_discussion"):
            if not (ROOT / "stages" / s["id"]).is_dir():
                problems.append(f"启用阶段 {s['id']} 缺 stages/ 目录")
    for seg in plan.get("segments", []) if plan.get("source") != "platform-published" else []:
        if not (ROOT / "lesson-data/segments" / f"{seg['id']}.json").is_file():
            problems.append(f"缺段落文件 {seg['id']}.json")
    return problems


def tick(state: ClassroomState) -> dict:
    """唯一读时间的地方（规范第 5 节）。同时是每轮的复位点：清掉上一轮的
    证据 / 星级更新 / 判决 / 回复，防止旧值渗入本轮判定。

    `reply_text` 必须每轮清空：心跳轮大多是静默的（不说话），如果留着上一轮的话，
    上层会以为本轮又说了同一句，界面上重复刷屏。
    """
    now = datetime.fromisoformat(state["now"])
    # time_scale 由会话层注入，不在这里读环境变量 —— 图保持纯函数，可复用、可回放。
    # >1 时分钟数按倍率放大：课前演练用 12 倍就能把 45 分钟的课压缩到 4 分钟验证。
    scale = float(state.get("time_scale") or 1.0)

    def minutes_since(t: str | None) -> float:
        if not t:
            return 0.0
        return round((now - datetime.fromisoformat(t)).total_seconds() / 60 * scale, 2)

    return {
        "stage_elapsed_minutes": minutes_since(state.get("stage_started_at")),
        "lesson_elapsed_minutes": minutes_since(state.get("lesson_started_at")),
        "turn_evidence": [],
        "mastery_updates": [],
        "target_phase": None,
        "advance_reason": None,
        "reply_text": "",
    }


def load_context(state: ClassroomState) -> dict:
    """分层装配上下文（规范第 4 节）。空壳阶段注入占位提示，不报错；
    进入复述/探究阶段时按三级兜底链组装问题队列。"""
    phase = state.get("host_phase")
    parts: list[str] = []

    # 计划层（仅当前阶段配置）
    plan = state.get("lesson_plan") or {}
    from apps.integration import prompt_context

    platform_context = prompt_context.tutor_context(state)
    if platform_context:
        parts.append("[已发布课程上下文]\n" + platform_context)
    else:
        # 独立 demo 模式继续使用仓库内课程文件。
        parts.append("[知识库]\n" + _read("rules/KNOWLEDGE-BASE.md"))
    for s in plan.get("stages", []):
        if s["id"] == phase:
            parts.append(f"[阶段计划] {s}")
    # 课堂层：当前 segment + 绑定的 KP 全文
    if state.get("active_segment_id"):
        platform_segment = prompt_context.segment_by_id(plan, state["active_segment_id"])
        seg_text = (
            json.dumps(platform_segment, ensure_ascii=False)
            if platform_segment
            else _read(f"lesson-data/segments/{state['active_segment_id']}.json")
        )
        parts.append("[当前段落]\n" + seg_text)
    # 阶段层（只有复述/探究/讨论三幕有；空壳 → 占位提示）
    if phase in ("recap_discussion", "deep_inquiry", "class_discussion") and not platform_context:
        for f in ("questions.md", "prompt.md", "rubric.md"):
            text = _read(f"stages/{phase}/{f}")
            parts.append(f"[{f}]\n" + (text.strip() or "[本阶段内容未配置]"))
    # 档案层
    parts.append("[掌握档案]\n" + json.dumps(state.get("kp_stars", {}), ensure_ascii=False))

    updates: dict = {"assembled_prompt": "\n\n".join(parts)}

    # 进入提问阶段 → 组装问题队列 + 未关闭目标
    if phase in ("recap_discussion", "deep_inquiry") and not state.get("question_queue"):
        queue = build_question_queue(phase, state.get("unresolved") or [], plan)
        updates["question_queue"] = queue
        updates["q_index"] = 0
        updates["unresolved"] = [q["kp_id"] for q in queue]
    elif phase == "guided_learning" and not state.get("unresolved"):
        # 讲解阶段的"未关闭目标" = 全部段落涉及的 KP（讲过 ≠ 关闭）
        kps: list[str] = []
        for seg in plan.get("segments", []):
            if prompt_context.is_platform_plan(plan):
                kps.extend(seg.get("knowledge_point_ids", []))
            else:
                try:
                    seg_data = json.loads(
                        (ROOT / "lesson-data/segments" / f"{seg['id']}.json")
                        .read_text(encoding="utf-8")
                    )
                    kps.extend(seg_data.get("knowledge_point_ids", []))
                except FileNotFoundError:
                    pass
        updates["unresolved"] = list(dict.fromkeys(kps))

    return updates


def classify_turn(state: ClassroomState) -> dict:
    """判断本轮是谁在说话：host → 主持事件；student → 教学轮。

    心跳轮（tick_only）没有学生输入，但**仍然算 host**：它代表时间在流逝，
    不代表学生在答题。路由会把心跳送到教学层（见 route_after_classify），
    要不要真的说话由 teach 决定。
    """
    if state.get("tick_only"):
        return {"speaker": "host"}
    is_host = state.get("speaker") == "host" or not state.get("student_message")
    return {"speaker": "host" if is_host else "student"}


def host_event(state: ClassroomState) -> dict:
    """处理主持事件：开场（intro）与课程中的主持人插话。"""
    phase = state.get("host_phase")
    plan = state.get("lesson_plan") or {}
    if phase == "intro":
        enabled = [s for s in plan.get("stages", []) if s.get("enabled")]
        agenda = "，".join(
            f"{STAGE_NAMES.get(s['id'], s['id'])}{s['minutes']}分钟" for s in enabled
        )
        lead = (
            "这节课的讲解部分是一段视频，看完我们再一起复述和深入讨论。"
            if stage_delivery(state) == "video" else
            "我会根据你的掌握情况调整节奏——听懂了我们就往前走，没听透我会多问几句。"
        )
        reply = (
            f"上课！今天我们讲「{plan.get('lesson_title', state['lesson_id'])}」，"
            f"共 {plan.get('total_minutes')} 分钟。\n"
            f"流程：{agenda}。\n"
            f"{lead}"
        )
        return {"reply_text": reply, "student_status": "active"}
    if phase == "ending":
        return {"reply_text": "这节课就到这里，下课！"}
    return {"reply_text": "（老师插话）好，我们继续。"}


def _segments(plan: dict) -> list[dict]:
    return plan.get("segments") or []


def _segment_at(plan: dict, cursor: int) -> dict | None:
    """按游标取段落详情。"""
    segs = _segments(plan)
    if cursor < 0 or cursor >= len(segs):
        return None
    platform_segment = segs[cursor] if plan.get("source") == "platform-published" else None
    if platform_segment:
        return platform_segment
    sid = segs[cursor]["id"]
    try:
        return json.loads(
            (ROOT / "lesson-data/segments" / f"{sid}.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _cursor_for_elapsed(plan: dict, elapsed: float) -> int:
    """按累计段落时长算出该讲到第几段（时间驱动的推进）。超过总长返回 len(segments)。"""
    cum = 0.0
    for i, seg in enumerate(_segments(plan)):
        cum += seg.get("minutes", 0)
        if elapsed < cum:
            return i
    return len(_segments(plan))


def _next_cursor(plan: dict, state: ClassroomState, elapsed: float) -> int:
    """讲解阶段段落游标的推进：取两种驱动源的较大值，游标只增不减。

    两个驱动源：
      - **时间**：该讲到这里了（心跳到点自动推进）
      - **外部事件 media_done**：这段视频播完了，不用等时间，直接讲下一段
    """
    base = int(state.get("segment_cursor") or 0)
    by_time = _cursor_for_elapsed(plan, elapsed)
    cursor = max(base, by_time)
    if state.get("external_event") == EVENT_MEDIA_DONE:
        cursor = max(cursor, base + 1)
    return cursor


def _segment_by_id(plan: dict, seg_id: str | None) -> dict | None:
    """按 id 取段落（用于"同一段继续讲"时给模型一个内容锚点）。"""
    if not seg_id:
        return None
    from apps.integration import prompt_context

    platform_segment = prompt_context.segment_by_id(plan, seg_id)
    if platform_segment:
        return platform_segment
    try:
        return json.loads(
            (ROOT / "lesson-data/segments" / f"{seg_id}.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _segment_titles(plan: dict) -> list[str]:
    """本阶段所有段落标题 —— 收尾总结时给模型列出范围，防止自由发挥。"""
    titles = []
    for seg in plan.get("segments", []):
        d = _segment_by_id(plan, seg.get("id"))
        if d:
            titles.append(d.get("title", seg["id"]))
    return titles


def llm_polish(state: ClassroomState, directive: str) -> str | None:
    """把编排骨架算好的"本轮指令"润色成自然语言。

    关键：**模型不决定讲什么、问什么** —— 那些由 `_teach_skeleton` 算好后传进来。
    模型只负责表达。所以接不接模型，切幕时机与星级判定完全一致；
    模型挂了也只是"话说得朴素点"，课照常上完。
    """
    phase = state.get("host_phase")
    elapsed = state.get("stage_elapsed_minutes", 0.0)
    budget = state.get("stage_budget_minutes", 0.0)
    from apps.integration import prompt_context

    course_context = prompt_context.tutor_context(state)
    return llm_chat(
        "你是一名课堂智能体，正在给学生上课。"
        "严格按【本轮指令】执行：不要偏离、不要另起话题、不要提指令里没有的新问题。"
        "只能使用【已发布课程事实】中的课程内容，不得使用其他课程或自行补充事实。"
        "要求：中文口语，2-5 句，不写标题、不用 Markdown、不要括号注释。",
        f"当前阶段：{STAGE_NAMES.get(phase, phase)}（已进行 {elapsed:.0f}/{budget:.0f} 分钟）\n"
        f"【已发布课程事实】\n{course_context or '独立演示模式：使用本地课程文件'}\n\n"
        f"【本轮指令】\n{directive}\n\n"
        f"学生刚才说：{state.get('student_message', '') or '（未发言）'}\n\n"
        f"直接输出你要说的话：",
    )


def stage_opening(state: ClassroomState, next_phase: str) -> tuple[str, bool]:
    """切幕时说给学生听的开场白。

    返回 (文本, 是否由大模型生成)。模型不可用时降级为模板句——
    切幕这件事本身照常发生，不会因为没有模型就卡住。
    """
    name = STAGE_NAMES.get(next_phase, next_phase)
    goal = STAGE_GOAL.get(next_phase, "我们继续")
    # 视频模式下讲解环节的开场白：提醒看视频，而不是"我带你过一遍"
    if next_phase == "guided_learning" and stage_delivery(state) == "video":
        goal = "接下来请看本节课的讲解视频，看完我们再一起复述和讨论"
    plain = f"好，我们进入「{name}」。{goal}。"
    if not llm_available():
        return plain, False
    polished = llm_chat(
        "你是一名课堂智能体。用一两句话自然宣布进入下一个教学环节。"
        "中文口语，不要用 Markdown，不要提具体几分钟。",
        f"即将进入的环节：{name}\n"
        f"这一环节要做的事：{goal}\n\n"
        f"直接输出你要说的话：",
    )
    return (polished.strip(), True) if polished else (plain, False)


def teach(state: ClassroomState) -> dict:
    """本幕教学（规范第 3 节 teach 节点）。

    分两层，**这样拆是为了让编排不被模型影响**：
      1. `_teach_skeleton` 在本函数体内先算出：讲哪一段 / 问哪一题 / 给什么反馈。
         这部分永远执行 —— 接不接 LLM 都不影响切幕与星级。
      2. LLM 润色（可选）：只把上面算好的指令变成自然语言。
         失败就用朴素文案，编排状态一字不差。
    """
    phase = state.get("host_phase")
    msg = state.get("student_message", "")
    elapsed = state.get("stage_elapsed_minutes", 0.0)
    budget = state.get("stage_budget_minutes", 0.0)
    plan = state.get("lesson_plan") or {}

    updates: dict = {"attempts": state.get("attempts", 0)}
    plain = ""
    directive = ""
    # 心跳轮默认静默；只有下面明确置 True 的分支（讲到新段落 / 抛出新一问）才开口。
    # 否则每隔几秒就重复一句"很好，我们接着往下讲"，课堂上没法听。
    tick = bool(state.get("tick_only"))
    speak = not tick

    # 老师按「下一环节」：本轮 teach 不说话，由 advance_stage 的开场白接管。
    # 否则会拼出"刚抛出一个问题、下一秒又宣布换环节"的缝合怪回复。
    if state.get("external_event") == EVENT_NEXT_STAGE:
        return {"reply_text": "", "llm_used": False,
                "attempts": state.get("attempts", 0)}

    # 预算耗尽且策略为 wrap_up → 本轮先收尾再切幕
    wrap = (
        elapsed >= budget
        and budget > 0
        and state.get("on_budget_exhausted") == "wrap_up"
        and phase in STAGE_NAMES
    )
    wrap_line = "好，这一段的时间到了，我们收个尾。\n" if wrap else ""

    # ── 第一层：确定性编排骨架（永远执行）──
    if phase == "guided_learning":
        # ── 视频讲解模式：一整段视频替代 AI 讲解 ──
        # AI 全程不出讲解词；唯一要做的事：视频播完那一刻把段落游标推满
        # （judge_advance 看到"素材全部播完"会切进下一环节）。
        if stage_delivery(state) == "video":
            if state.get("external_event") == EVENT_MEDIA_DONE:
                segs = _segments(plan)
                updates["segment_cursor"] = len(segs)
                played = [
                    {"segment_id": s.get("id"), "at": state.get("now")}
                    for s in segs
                ]
                updates["played_media"] = list(state.get("played_media") or []) + played
            updates["reply_text"] = ""
            updates["llm_used"] = False
            return updates

        cursor = _next_cursor(plan, state, elapsed)
        if cursor != state.get("segment_cursor", 0):
            updates["segment_cursor"] = cursor
        if state.get("external_event") == EVENT_MEDIA_DONE:
            # 记一笔"这段素材播完了"，学情导出用得上
            prev = _segment_at(plan, int(state.get("segment_cursor") or 0))
            if prev:
                played = list(state.get("played_media") or [])
                played.append({"segment_id": prev["segment_id"], "at": state.get("now")})
                updates["played_media"] = played
        seg = _segment_at(plan, cursor)
        if seg and seg["segment_id"] != state.get("active_segment_id"):
            updates["active_segment_id"] = seg["segment_id"]
            speak = True              # 讲到新段落了，这一句必须说
            kps = "、".join(seg.get("knowledge_point_ids", []))
            plain = (
                f"{wrap_line}[第{seg['order']}段] {seg['title']}\n"
                f"{seg['content']}\n"
                f"（涉及知识点：{kps}）"
            )
            directive = (
                f"讲解第{seg['order']}段《{seg['title']}》。\n"
                f"必须讲清楚的要点：{seg['content']}\n"
                f"涉及知识点：{kps}。\n"
                f"讲完后确认学生是否跟上。"
            )
        else:
            if wrap:
                speak = True          # 本幕时间到，收个尾（说完就切幕）
            plain = wrap_line + "很好，我们接着往下讲。"
            # ⚠️ directive 必须带内容锚点。曾经这里只写"往深讲一层"，
            #    模型没有任何范围约束，直接编出了"马尔可夫性质、参数估计"
            #    （本课是处理机调度）—— 幻觉。锚点是防这个的。
            if wrap:
                titles = "、".join(f"《{t}》" for t in _segment_titles(plan))
                directive = (
                    f"讲解阶段的时间到了。用一两句话总结本阶段讲过的内容：{titles}。\n"
                    f"只做回顾，**不要再讲任何新概念**，也不要超出上面这些标题的范围。"
                )
            else:
                cur = _segment_by_id(plan, state.get("active_segment_id"))
                anchor = (
                    f"当前段落《{cur.get('title')}》：{cur.get('content')}"
                    if cur else "处理机调度的基本概念"
                )
                directive = (
                    f"学生回应简短。简短肯定他，然后围绕下面这段内容再往深讲一层：\n"
                    f"{anchor}\n"
                    f"严格限制在这个范围内，不要引入上面没提到的新概念。"
                )
        updates["current_target"] = None
        updates["current_question"] = None

    elif phase == "intro":
        # 起课铃：事件轮走教学层（不进 host_event），开场白在这里说。
        # 只在收到 begin 事件时开口；intro 的其他轮次（心跳）静默等老师。
        if state.get("external_event") == EVENT_BEGIN:
            speak = True
            ev = host_event(state)          # 复用同一份开场白文案
            updates.update(ev)              # reply_text 模板 + student_status=active
            plain = ev["reply_text"]
            directive = (
                "课程刚开始。向学生宣布今天的课题与流程安排，"
                "语气自然、像老师开课那样简短。内容以这条为准：" + plain
            )

    elif phase in ("recap_discussion", "deep_inquiry"):
        queue = state.get("question_queue") or []
        pending = state.get("pending_question")
        idx = state.get("q_index", 0)
        lines: list[str] = [wrap_line] if wrap_line else []
        dl: list[str] = []                      # 给 LLM 的指令分段

        if pending:
            # 学生回答了上一轮挂起的问题 → 反馈
            kp = pending["kp_id"]
            hits, total = match_evidence(kp, msg, state)
            updates["current_target"] = kp
            if total and hits == total:
                lines.append("很好，说得很完整！")
                dl.append("学生刚才答得完整，先具体肯定他答对了什么。")
            elif hits > 0:
                lines.append(f"方向对了，但还差一点：{_hint(kp, state)}")
                dl.append(f"学生答对了一部分。肯定对的部分，再指出缺的是：{_hint(kp, state)}")
            else:
                updates["attempts"] = state.get("attempts", 0) + 1
                lines.append(f"再想想：{_hint(kp, state)}")
                lines.append(f"还是这个问题——{pending['question']}")
                dl.append(
                    f"学生没答上来。不要直接给答案，用这个提示引导：{_hint(kp, state)}\n"
                    f"然后把原题再问一遍：{pending['question']}"
                )
            if wrap:
                # 预算耗尽收尾：不再抛下一问，留给下一幕/下节课
                updates["pending_question"] = None
                lines.append("时间到了，这个问题我们先收在这里。")
                dl.append("本阶段时间到了，简短收尾。**绝对不要再提新问题**。")
            else:
                nxt = queue[idx + 1] if idx + 1 < len(queue) else None
                updates["q_index"] = idx + 1
                updates["pending_question"] = nxt
                updates["attempts"] = 0
                if nxt:
                    lead = "下一问：" if hits and total and hits == total else "这个我们先放一放，继续："
                    lines.append(f"{lead}{nxt['question']}")
                    dl.append(f"接着提出下一问：{nxt['question']}")
                else:
                    lines.append("这一阶段的问题就到这里。")
                    dl.append("本阶段问题已全部问完，做简短过渡。")
            updates["current_question"] = (updates.get("pending_question") or pending).get("question")
        elif queue and idx < len(queue):
            q = queue[idx]
            updates["pending_question"] = q
            updates["current_target"] = None
            updates["current_question"] = q["question"]
            speak = True              # 抛出新的一问：这是 AI 主动开口，不是等学生先说
            lead = (
                "这一阶段我想听听你的复述。"
                if phase == "recap_discussion" else "下面我们往深处挖一挖。"
            )
            lines.append(f"{lead}\n{q['question']}")
            dl.append(
                f"{'进入复述环节，说明你想听他用自己的话讲一遍' if phase == 'recap_discussion' else '进入深层探究，说明要往深处挖'}。"
                f"然后提出这一问：{q['question']}"
            )
        elif queue:
            lines.append("这一阶段的问题就到这里。")
            dl.append("本阶段问题已问完，做简短过渡。")
        else:
            lines.append("[本阶段内容未配置，且无可用问题]")
            dl.append("本阶段没有配置题目，简短过渡即可。")

        plain = "\n".join(x for x in lines if x)
        directive = "\n".join(dl)

    elif phase == "class_discussion":
        updates["current_target"] = None
        updates["current_question"] = None
        plain = wrap_line + "进入全班讨论，请老师主导。"
        directive = "宣布进入全班讨论环节，请老师来主导。"

    elif phase == "ending":
        stars = state.get("kp_stars", {})
        lines = ["这节课到这里。最后看一眼你的掌握情况："]
        for kp, st in sorted(stars.items()):
            lines.append(f"- {kp}：{'★' * st}（{STAR_STATUS.get(st, '未检测')}）")
        lines.append("下节课见！")
        # 用中文标题而非 KP 编号——模型会照着说，编号会直接念给学生听
        detail = "、".join(f"{kp_title(kp)} {s} 星" for kp, s in sorted(stars.items()))
        weak = [kp_title(kp) for kp, s in sorted(stars.items()) if s <= 2]
        plain = "\n".join(lines)
        directive = (
            "做下课总结：回顾本课学了什么，点出学生的掌握情况"
            f"（{detail}），"
            + (f"对还没掌握的部分（{'、'.join(weak)}）给一句课后建议。" if weak
               else "鼓励一下。")
            + "简短收尾，说下节课见。"
        )
        updates["student_status"] = "ended"

    else:
        plain = wrap_line + "……"
        directive = "简短回应学生。"

    # ── 心跳静默：本轮没有新内容，就不开口 ──
    if tick and not speak:
        updates["reply_text"] = ""
        updates["llm_used"] = False
        return updates

    # ── 第二层：LLM 只负责把指令变成自然语言（可失败）──
    if llm_available():
        polished = llm_polish(state, directive)
        if polished:
            updates["reply_text"] = polished.strip()
            updates["llm_used"] = True
            return updates

    updates["reply_text"] = plain
    updates["llm_used"] = False
    return updates


def _hint(kp_id: str, state: ClassroomState | None = None) -> str:
    from apps.integration import prompt_context

    if state:
        platform_hint = prompt_context.hint(state.get("lesson_plan") or {}, kp_id)
        if platform_hint:
            return platform_hint
    hints = {
        "KP-002": "想一想：作业是谁调进内存的？变成进程之后，又是谁决定它上 CPU？",
        "KP-003": "三个指标各有一个起点和一个终点，注意区分“第一次拿到 CPU”和“做完”。",
        "KP-004": "如果一直有短作业进来，长作业会怎样？HRRN 的响应比是怎么算的？",
        "KP-005": "关键是“正在运行的进程会不会被打断”，想想什么事件会触发打断。",
        "KP-006": "RR 拿什么换响应速度？多级反馈队列为什么不用预先知道进程长度？",
    }
    return hints.get(kp_id, "再从定义出发想一想。")


def judge_mastery(state: ClassroomState) -> dict:
    """按 MASTERY-STAR-RULES.md 判星级（确定性）。

    - guided_learning：讲过即记 1 星（已接触）
    - recap_discussion：零散要点 2 星 / 完整复述 3 星
    - deep_inquiry：说出机制 4 星
    - 星级只升不降；证据来自学生话语的关键词组匹配。
    """
    phase = state.get("host_phase")
    msg = state.get("student_message", "")
    kp_stars = dict(state.get("kp_stars") or {})
    kp_meta = dict(state.get("kp_meta") or {})
    updates: list[dict] = []
    evidence: list[str] = []
    mastered = list(state.get("mastered") or [])
    unresolved = list(state.get("unresolved") or [])
    now = state.get("now")

    def bump(kp: str, new_stars: int, source: str, ev: str) -> None:
        old = kp_stars.get(kp, 0)
        if new_stars > old:
            kp_stars[kp] = new_stars
            updates.append({
                "kp_id": kp, "old_stars": old, "new_stars": new_stars,
                "old_status": STAR_STATUS.get(old, "未检测"),
                "new_status": STAR_STATUS[new_stars],
                "source": source, "stage": phase, "evidence": ev,
                "occurred_at": now,
            })
            kp_meta[kp] = {
                "last_source": source, "last_stage": phase,
                "last_evidence": ev, "updated_at": now,
            }

    if phase == "guided_learning":
        seg_id = state.get("active_segment_id")
        seg = None
        if seg_id:
            plan = state.get("lesson_plan") or {}
            if plan.get("source") == "platform-published":
                seg = next((s for s in plan.get("segments", []) if s["segment_id"] == seg_id), None)
            if seg is None:
                try:
                    seg = json.loads(
                        (ROOT / "lesson-data/segments" / f"{seg_id}.json").read_text(encoding="utf-8")
                    )
                except FileNotFoundError:
                    seg = None
            if seg:
                for kp in seg.get("knowledge_point_ids", []):
                    bump(kp, 1, "dialogue", f"讲解阶段讲过（{seg['title']}）")

    elif phase in ("recap_discussion", "deep_inquiry"):
        kp = state.get("current_target")
        if kp:
            hits, total = match_evidence(kp, msg, state)
            if total:
                if phase == "recap_discussion":
                    new_stars = 3 if hits == total else (2 if hits > 0 else 0)
                else:
                    new_stars = 4 if hits == total else 0
                if new_stars:
                    ev = f"学生原话：「{msg[:60]}」"
                    bump(kp, new_stars, "dialogue", ev)
                    evidence.append(f"{kp}: 命中 {hits}/{total} 组证据")
                    if hits == total:
                        if kp in unresolved:
                            unresolved.remove(kp)
                        if kp not in mastered:
                            mastered.append(kp)

    return {
        "mastery_updates": updates,
        "turn_evidence": evidence,
        "kp_stars": kp_stars,
        "kp_meta": kp_meta,
        "mastered": mastered,
        "unresolved": unresolved,
    }


def _next_phase(state: ClassroomState) -> str:
    rest = state.get("remaining_stages") or []
    return rest[0] if rest else "ending"


def judge_advance(state: ClassroomState) -> dict:
    """★ 编排核心（规范第 6 节）。判定顺序即优先级：证据优先于时间。"""
    phase = state.get("host_phase")

    if phase == "ending":
        return {"target_phase": None, "advance_reason": "课程已结束"}

    # ── 外部事件优先级最高：跳过最短时长、证据、预算三道门槛 ──
    ev = state.get("external_event")
    if ev == EVENT_NEXT_STAGE:
        return {"target_phase": _next_phase(state), "advance_reason": "老师按了「下一环节」"}
    if ev == EVENT_MEDIA_DONE and phase == "guided_learning":
        # 素材放完就往前走：还有段落 → 讲下一段（在 teach 里推进游标）；
        # 已是最后一段（游标越界）→ 素材讲完了，进入下一环节。
        total = len((state.get("lesson_plan") or {}).get("segments") or [])
        if state.get("segment_cursor", 0) >= total:
            return {"target_phase": _next_phase(state), "advance_reason": "讲解素材已全部播完"}

    if phase == "intro":
        return {"target_phase": _next_phase(state), "advance_reason": "开场完成"}

    # 视频讲解模式：讲解阶段只认「视频播完」或老师按钮，时间预算不切幕
    # （视频可能比阶段预算长，不能没放完就被时间赶去下一环节）
    if phase == "guided_learning" and stage_delivery(state) == "video" \
            and ev not in (EVENT_MEDIA_DONE, EVENT_NEXT_STAGE):
        return {"target_phase": None, "advance_reason": "等待讲解视频播放完成"}

    elapsed = state.get("stage_elapsed_minutes", 0.0)
    budget = state.get("stage_budget_minutes", 0.0)

    if elapsed < state.get("min_stage_minutes", 2.0):
        return {"target_phase": None, "advance_reason": "未达最短幕时长"}

    if state.get("advance_when") == "evidence" and state.get("unresolved"):
        return {"target_phase": None, "advance_reason": "尚有未关闭目标（evidence 模式）"}

    if state.get("turn_evidence") and not state.get("unresolved"):
        if (
            state.get("on_evidence_reached") == "advance"
            and state.get("advance_when") in ("evidence", "either")
        ):
            return {"target_phase": _next_phase(state), "advance_reason": "证据充分"}

    if elapsed >= budget:
        mode = state.get("on_budget_exhausted", "wrap_up")
        if mode == "force_advance":
            return {"target_phase": _next_phase(state), "advance_reason": "预算耗尽（force_advance）"}
        if mode == "wrap_up":
            return {"target_phase": _next_phase(state), "advance_reason": "预算耗尽（wrap_up 收尾后切幕）"}
        # extend：超时但仍在延长额度内 → 留幕
        overrun = elapsed - budget
        if overrun < state.get("max_stage_overrun_minutes", 3.0):
            return {"target_phase": None, "advance_reason": "预算超时但在延长额度内"}
        return {"target_phase": _next_phase(state), "advance_reason": "预算耗尽（extend 超限）"}

    return {"target_phase": None, "advance_reason": "时间与证据均未触发切幕"}


def advance_stage(state: ClassroomState) -> dict:
    """切幕三连（规范第 6 节）：写快照 → 取下一幕 → 重置本幕状态。"""
    phase = state.get("host_phase")
    now = state.get("now")
    plan = state.get("lesson_plan") or {}
    reply = state.get("reply_text", "")

    # 1) 阶段快照（intro/ending 不拍）
    snapshot = None
    if phase in STAGE_NAMES:
        snapshot = {
            "type": "stage_snapshot",
            "snapshot_id": f"ss-{len(state.get('stage_snapshots') or []) + 1:03d}",
            "student_id": state.get("student_id"),
            "lesson_id": state.get("lesson_id"),
            "stage": phase,
            "stage_elapsed_minutes": state.get("stage_elapsed_minutes"),
            "targets_closed": list(state.get("mastered") or []),
            "targets_open": list(state.get("unresolved") or []),
            "stars_snapshot": dict(state.get("kp_stars") or {}),
            "evidence": "；".join(state.get("turn_evidence") or []) or "本幕无文字证据",
            "occurred_at": now,
        }

    # 2) 取下一幕
    rest = list(state.get("remaining_stages") or [])
    if not rest:
        # 总结要算上本幕（deep_inquiry）刚拍的这条快照
        remark, gen = _ending_remark(state, snapshot)
        out = {
            "host_phase": "ending",
            "remaining_stages": [],
            "stage_started_at": now,
            "stage_elapsed_minutes": 0.0,
            "stage_budget_minutes": 0.0,
            "current_target": None,
            "current_question": None,
            "pending_question": None,
            "question_queue": [],
            "q_index": 0,
            "mastered": [],
            "unresolved": [],
            "reply_text": (reply + "\n\n" + remark).strip(),
            "advance_reason": state.get("advance_reason"),
            "llm_used": gen,
            # 到 ending 就下课：会话层看到这个标记会停掉心跳线程
            "student_status": "ended",
        }
        if snapshot:
            out["stage_snapshots"] = [snapshot]
        return out

    nxt = rest[0]
    stage_cfg = next((s for s in plan.get("stages", []) if s["id"] == nxt), {})
    # 未关闭的目标带进下一幕（如复述阶段没答透的难点，探究阶段优先追问）
    carried = list(state.get("unresolved") or [])
    # 切幕要说一句人话告诉学生换环节了；原先这里写的是内部日志 [切幕] 进入X（预算 n 分钟），
    # 会直接显示给学生，既有编号味又说漏了不该让学生操心的预算。
    # 例外：video 模式切进讲解阶段**不开口**——起课铃一响直接放视频，
    # AI 第一句话留给复述板块（有头有尾从那里开始）。
    if nxt == "guided_learning" and stage_delivery(state) == "video":
        opening, gen = "", False
    else:
        opening, gen = stage_opening(state, nxt)
    out = {
        "host_phase": nxt,
        "remaining_stages": rest[1:],
        "stage_budget_minutes": float(stage_cfg.get("minutes", 0)),
        "advance_when": stage_cfg.get("advance_when", "either"),
        "stage_started_at": now,
        "stage_elapsed_minutes": 0.0,
        "current_target": None,
        "current_question": None,
        "pending_question": None,
        "question_queue": [],
        "q_index": 0,
        "attempts": 0,
        "mastered": [],
        "unresolved": carried if nxt in ("deep_inquiry", "class_discussion") else [],
        "active_segment_id": None,
        "reply_text": (reply + ("\n\n" if reply and opening else "") + opening).strip(),
        "advance_reason": state.get("advance_reason"),
        "llm_used": gen,
    }
    # 进入提问阶段：当场把第一问挂起来并说出口。不然前端拿到 current_question=None，
    # 老师按节奏切幕后学生干等一轮心跳（默认 10 秒）才听到题目。
    if nxt in ("recap_discussion", "deep_inquiry"):
        queue = build_question_queue(nxt, carried, plan)
        if queue:
            out["question_queue"] = queue
            out["q_index"] = 0
            out["pending_question"] = queue[0]
            out["current_question"] = queue[0]["question"]
            out["unresolved"] = [q["kp_id"] for q in queue]
            out["reply_text"] = (
                out["reply_text"] + f"\n\n先来第一问：{queue[0]['question']}"
            )
    if snapshot:
        out["stage_snapshots"] = [snapshot]
    return out


def _ending_remark(state: ClassroomState, pending_snapshot: dict | None) -> tuple[str, bool]:
    """下课那句话。能用模型就说人话，不能用就退回模板。

    为什么不等下一轮 teach 再说：切进 ending 就要立刻把 student_status 置为 ended，
    会话层据此停心跳——晚了这句话就永远没人替老师说了。
    """
    plain = _ending_summary(state, pending_snapshot=pending_snapshot)
    if not llm_available():
        return plain, False
    stars = state.get("kp_stars") or {}
    detail = "、".join(f"{kp_title(kp)} {v} 星" for kp, v in sorted(stars.items()))
    weak = [kp_title(kp) for kp, v in sorted(stars.items()) if v <= 2]
    polished = llm_chat(
        "你是一名课堂智能体，正在宣布下课。",
        f"本课知识点掌握情况：{detail or '（本课没有采集到证据）'}\n"
        + (f"还没掌握好的：{'、'.join(weak)}。\n" if weak else "全部达到理解线以上。\n")
        + "要求：中文口语，3-5 句。先回顾本课学了什么，再点出课后该补的地方，"
          "最后说下节课见。不要用 Markdown、不要罗列编号。",
    )
    return (polished.strip(), True) if polished else (plain, False)


def _ending_summary(state: ClassroomState, pending_snapshot: dict | None = None) -> str:
    """下课总结的降级文案（没接 LLM 时走这条）。

    这段文字会直接念给学生听，所以要守两条：
      · 只用 kp_title() 的中文标题，**不能出现 KP-xxx 内部编号**
        （MASTERY-STAR-RULES.md 明写「不能把 KP-004 这类内部编号说给学生听」）；
      · 不带 [下课总结] 这类内部日志标记 —— 那是写日志用的，不是给人念的。
        之前 [切幕] 踩过同一个坑，见 .workbuddy/memory。
    """
    stars = state.get("kp_stars") or {}
    snaps = list(state.get("stage_snapshots") or [])
    if pending_snapshot:
        snaps = snaps + [pending_snapshot]
    lines = [
        f"这节课就到这里。本课计划 {state.get('lesson_plan', {}).get('total_minutes')} 分钟，"
        f"实际上了 {state.get('lesson_elapsed_minutes')} 分钟，共 {len(snaps)} 幕。"
    ]
    if stars:
        lines.append("掌握情况：")
        for kp, st in sorted(stars.items()):
            lines.append(f"  · {kp_title(kp)}：{'★' * st}（{STAR_STATUS.get(st, '未检测')}）")
    open_kps = [kp_title(kp) for kp, st in stars.items() if st < 3]
    if open_kps:
        lines.append(f"建议课后补一补：{('、'.join(open_kps))}。")
    lines.append("下节课见。")
    return "\n".join(lines)


def write_state(state: ClassroomState) -> dict:
    """落盘（规范第 3 节）：DIALOGUE-LOG.md + dialogue-log.json +
    mastery-state.json + mastery-history.json（追加，不覆盖历史）。"""
    try:
        _write_dialogue_log(state)
        # 心跳轮不进对话流水：一节课上百次心跳会把流水撑满空记录，学情导出全是噪音。
        # 而掌握档案是幂等覆盖写的，重复写没有副作用。
        if not state.get("tick_only"):
            _append_dialogue_json(state)
        _write_mastery_state(state)
        _append_mastery_history(state)
    except Exception as e:  # 落盘失败不阻断教学回复
        return {"reply_text": state.get("reply_text", "") + f"\n[warn] 落盘失败: {e}"}
    return {}


def _write_dialogue_log(state: ClassroomState) -> None:
    content = f"""# DIALOGUE-LOG

## 会话状态
- student_id: {state.get('student_id')}
- lesson_id: {state.get('lesson_id')}
- speaker: {state.get('speaker')}

### 编排器
- host_phase: {state.get('host_phase')}
- active_segment_id: {state.get('active_segment_id') or '无'}
- now: {state.get('now')}
- lesson_started_at: {state.get('lesson_started_at') or '无'}
- stage_started_at: {state.get('stage_started_at') or '无'}
- stage_elapsed_minutes: {state.get('stage_elapsed_minutes')}
- lesson_elapsed_minutes: {state.get('lesson_elapsed_minutes')}
- stage_budget_minutes: {state.get('stage_budget_minutes')}
- remaining_stages: {state.get('remaining_stages') or '无'}
- advance_reason: {state.get('advance_reason') or '无'}

### 教学
- phase: {STAGE_NAMES.get(state.get('host_phase'), state.get('host_phase'))}
- current_target: {state.get('current_target') or '无'}
- current_question: {state.get('current_question') or '无'}
- attempts: {state.get('attempts', 0)}
- mastered: {state.get('mastered') or '无'}
- unresolved: {state.get('unresolved') or '无'}

### 学生
- student_status: {state.get('student_status')}

## 本轮证据
{(chr(10) + '- ').join(state.get('turn_evidence') or ['（无）'])}

## 下次重点
- {state.get('unresolved') and '继续追问未关闭目标：' + '、'.join(state['unresolved']) or '无'}
"""
    (ROOT / "runtime/DIALOGUE-LOG.md").write_text(content, encoding="utf-8")


def _append_dialogue_json(state: ClassroomState) -> None:
    path = ROOT / "runtime/data/dialogue-log.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["student_id"] = state.get("student_id")
    data["session_id"] = state.get("session_id")
    data["messages"].append({
        "turn_at": state.get("now"),
        "phase": state.get("host_phase"),
        "speaker": state.get("speaker"),
        "student_message": state.get("student_message", ""),
        "reply_text": state.get("reply_text", ""),
        "advance_reason": state.get("advance_reason"),
    })
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _student_dir(state: ClassroomState) -> Path:
    """每个学生一个目录（runtime/students/<student_id>/），掌握档案按学生隔离。

    ⚠️ 2026-09-21 实测中招：星级基线曾读共享的 runtime/data/mastery-state.json，
    导致上一个学生的星级渗进下一个学生的新会话。学生档案必须按 student_id 分开。
    """
    raw = str(state.get("student_id") or "default")
    safe = re.sub(r"[^\w\-.]", "_", raw)
    return ROOT / "runtime" / "students" / safe


def _write_mastery_state(state: ClassroomState) -> None:
    d = _student_dir(state)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "mastery-state.json"
    data: dict = {"student_id": state.get("student_id"),
                  "updated_at": None, "knowledge_points": {}}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    data["student_id"] = state.get("student_id")
    data["updated_at"] = state.get("now")
    kps = data.get("knowledge_points") or {}
    for kp, stars in (state.get("kp_stars") or {}).items():
        meta = (state.get("kp_meta") or {}).get(kp, {})
        rec = kps.get(kp) or {"assessment_status": "未考核"}
        rec.update({
            "kp_id": kp,
            "stars": stars,
            "status": STAR_STATUS.get(stars, "未检测"),
            "last_source": meta.get("last_source", rec.get("last_source", "dialogue")),
            "last_stage": meta.get("last_stage", rec.get("last_stage")),
            "last_evidence": meta.get("last_evidence", rec.get("last_evidence")),
            "updated_at": state.get("now"),
        })
        kps[kp] = rec
    data["knowledge_points"] = kps
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_mastery_history(state: ClassroomState) -> None:
    d = _student_dir(state)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "mastery-history.json"
    hist: list = []
    if path.is_file():
        try:
            hist = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            hist = []
    existing_changes = sum(1 for h in hist if h.get("type") == "mastery_change")
    for i, upd in enumerate(state.get("mastery_updates") or [], start=1):
        hist.append({
            "type": "mastery_change",
            "history_id": f"mh-{existing_changes + i:03d}",
            "student_id": state.get("student_id"),
            **upd,
        })
    # 快照按条数去重：state 里累计的快照数多于文件里已有的 → 补写新增部分
    existing_snaps = sum(1 for h in hist if h.get("type") == "stage_snapshot")
    for snap in (state.get("stage_snapshots") or [])[existing_snaps:]:
        hist.append(snap)
    path.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")


def format_reply(state: ClassroomState) -> dict:
    """组装最终回复与播报标记。"""
    reply = state.get("reply_text", "")
    return {"reply_text": reply, "speech_kind": "auto" if reply else "none"}


# ═══════════════════════════════════════════════════════════════
# 路由：判断写进 state，路由函数只读不判
# ═══════════════════════════════════════════════════════════════

def route_after_classify(state: ClassroomState) -> str:
    """心跳与外部事件都走教学层：游标推进、静默判定、切幕依据全在 teach/judge 里。
    走 host_event 的话 media_done 的游标推进根本不会执行（那边只管开场白和插话），
    表现为"视频播完报了却没切幕"——踩过一次，别再犯。

    是否真的开口由 teach 判断——没新内容就静默（reply_text 为空）。
    """
    if state.get("external_event") in (EVENT_MEDIA_DONE, EVENT_NEXT_STAGE):
        return "teach"
    if state.get("tick_only"):
        return "teach"
    return "host_event" if state.get("speaker") == "host" else "teach"


def route_after_judge(state: ClassroomState) -> str:
    return "next_stage" if state.get("target_phase") else "stay"


# ═══════════════════════════════════════════════════════════════
# 建图
# ═══════════════════════════════════════════════════════════════

def build_graph(checkpointer=None):
    g = StateGraph(ClassroomState)

    g.add_node("load_plan", load_plan)
    g.add_node("tick", tick)
    g.add_node("load_context", load_context)
    g.add_node("classify_turn", classify_turn)
    g.add_node("host_event", host_event)
    g.add_node("teach", teach)
    g.add_node("judge_mastery", judge_mastery)
    g.add_node("judge_advance", judge_advance)
    g.add_node("advance_stage", advance_stage)
    g.add_node("write_state", write_state)
    g.add_node("format_reply", format_reply)

    g.add_edge(START, "load_plan")
    g.add_edge("load_plan", "tick")
    g.add_edge("tick", "load_context")
    g.add_edge("load_context", "classify_turn")

    g.add_conditional_edges(
        "classify_turn", route_after_classify,
        {"host_event": "host_event", "teach": "teach"},
    )
    g.add_edge("host_event", "judge_advance")
    g.add_edge("teach", "judge_mastery")
    g.add_edge("judge_mastery", "judge_advance")

    g.add_conditional_edges(
        "judge_advance", route_after_judge,
        {"stay": "write_state", "next_stage": "advance_stage"},
    )
    g.add_edge("advance_stage", "write_state")
    g.add_edge("write_state", "format_reply")
    g.add_edge("format_reply", END)

    return g.compile(checkpointer=checkpointer)


# ═══════════════════════════════════════════════════════════════
# 会话层接口：每轮注入 now + 学生消息，同一个 thread_id 续上
# ═══════════════════════════════════════════════════════════════

def initial_state(session_id: str, student_id: str = "student-001",
                  lesson_id: str = "ch3-process-scheduling") -> dict:
    """新会话的首轮要传完整初始 state（后续轮从 checkpoint 恢复）。"""
    return {
        "session_id": session_id,
        "student_id": student_id,
        "lesson_id": lesson_id,
        "platform": {},
        "learning_context": {},
        "host_phase": "uninitialized",
        "active_segment_id": None,
        "stage_started_at": None,
        "stage_elapsed_minutes": 0.0,
        "lesson_elapsed_minutes": 0.0,
        "stage_budget_minutes": 0.0,
        "remaining_stages": [],
        "advance_when": "either",
        "now": "",
        "lesson_started_at": None,
        "tick_only": False,
        "time_scale": 1.0,
        # idle：会话建好了但老师还没点"开始上课"。这段时间由会话层兜着不跑编排，
        # 所以课时不会流逝。begin 事件把它置为 running（会话层改，图不感知细节）。
        "lesson_status": "idle",
        "external_event": None,
        "segment_cursor": 0,
        "played_media": [],
        "on_budget_exhausted": "wrap_up",
        "on_evidence_reached": "advance",
        "min_stage_minutes": 2.0,
        "max_stage_overrun_minutes": 3.0,
        "current_target": None,
        "current_question": None,
        "pending_question": None,
        "question_queue": [],
        "q_index": 0,
        "attempts": 0,
        "mastered": [],
        "unresolved": [],
        "student_message": "",
        "speaker": "student",
        "student_status": "waiting",
        "turn_evidence": [],
        "mastery_updates": [],
        "kp_stars": {},
        "kp_meta": {},
        "stage_snapshots": [],
        "reply_text": "",
        "speech_kind": "none",
        "advance_reason": None,
        "target_phase": None,
        "assembled_prompt": "",
        "lesson_plan": {},
        "llm_used": False,
    }


def run_one_turn(graph, session_id: str, now: str, message: str,
                 speaker: str = "student", tick_only: bool = False,
                 time_scale: float = 1.0,
                 external_event: str | None = None) -> dict:
    """跑一轮（依赖 checkpointer）。返回这轮结束后的完整 state（含 reply_text）。"""
    config = {"configurable": {"thread_id": session_id}}
    if not graph.get_state(config).values:
        payload = {**initial_state(session_id)}
    else:
        payload = {}
    # 本轮新增输入最后写入，覆盖初始占位值
    payload.update({
        "now": now, "student_message": message, "speaker": speaker,
        "tick_only": tick_only, "time_scale": time_scale,
        "external_event": external_event,
    })
    graph.invoke(payload, config)
    return dict(graph.get_state(config).values)


def run_turn_stateless(graph, state: dict, now: str, message: str,
                       speaker: str = "student", tick_only: bool = False,
                       time_scale: float = 1.0,
                       external_event: str | None = None) -> dict:
    """不带 checkpointer 跑一轮：由**会话层**持有 state，每轮全量回灌。

    为什么不用 checkpointer：`langgraph-checkpoint-sqlite` 在本机装不上，
    而 `load_plan` 是幂等的（host_phase 已初始化时直接返回空），所以把上一轮
    的完整 state 注入进去就能续上，持久化只需要写一个 JSON 文件。
    """
    payload = {
        **state,
        "now": now, "student_message": message, "speaker": speaker,
        "tick_only": tick_only, "time_scale": time_scale,
        # 每轮显式覆盖：这是本轮输入的一部分，留着旧值会连着触发好几次切幕
        "external_event": external_event,
    }
    return dict(graph.invoke(payload))


if __name__ == "__main__":
    graph = build_graph()
    print("图编译成功，节点结构：\n")
    print(graph.get_graph().draw_ascii())
