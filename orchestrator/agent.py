"""主动引导智能体 —— 真实 LangGraph 编排器实现。

依据 `orchestrator/ORCHESTRATOR.md` 规范实现，覆盖全部 11 个节点：
load_plan / tick / load_context / classify_turn / host_event / teach /
judge_mastery / judge_advance / advance_stage / write_state / format_reply

关键约定（与规范一致）：
- `now` 由会话层注入 state，图内任何节点不调 datetime.now() → 可单测、可回放。
- 判断写进 state（target_phase），路由函数只读不判。
- `stage_snapshots` 用 Annotated[list, operator.add] 累加，不覆盖。
- 空壳降级：复述阶段问题取 TMISSION 检验问题 → KNOWLEDGE-BASE 检测问题；探究阶段另读 stages/deep_inquiry/questions.md。

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


def kp_title(kp_id: str, lesson_id: str | None = None) -> str:
    """KP 编号 → 中文标题。

    上传的课时先查**它自己的**知识点（老师填的 `title`）—— 否则老师传的标题
    全被忽略，下课总结和课后报告里会出现 "KP-901（KP-901，★）" 这种重号。
    其余情况取自 KNOWLEDGE-BASE.md 的 `## KP-001 调度是什么`。

    模型生成的回复要用标题，**不能把 KP-004 这类内部编号说给学生听**。
    取不到时原样返回编号（宁可说编号，也不要编标题）。
    """
    if lesson_id and is_uploaded_lesson(lesson_id):
        lesson = load_lesson(lesson_id)
        for kp in (lesson[0].get("knowledge_points") or []) if lesson else []:
            if kp.get("kp_id") == kp_id:
                return str(kp.get("title") or kp_id)
        return kp_id

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


def match_evidence(kp_id: str, text: str) -> tuple[int, int]:
    """返回 (命中的证据组数, 总组数)。"""
    groups = EVIDENCE_GROUPS.get(kp_id, [])
    if not groups:
        return (0, 0)
    hits = sum(1 for g in groups if any(kw in text for kw in g))
    return (hits, len(groups))


# 复述阶段的学生状态。名字必须与 rules/interaction/RECAP-GUIDE.md 的
# `## 状态：<名字>` 小节一致 —— 那份文件就是靠这个对上号的。
STATE_CLEAR = "讲清楚了"
STATE_PARTIAL = "部分理解"
STATE_BLANK = "完全不会"
STATE_NO_RUBRIC = "没有评定标准"
MAX_DEEP_INQUIRY_ATTEMPTS = 5


def judge_state(hits: int, total: int) -> str:
    """把证据命中情况映射成状态名（对应 RECAP-GUIDE.md 的一节）。

    ⚠️ **`total == 0` 不是"学生没答上来"**，而是"这个知识点没有证据表"。
    `EVIDENCE_GROUPS` 只覆盖内置课时的 KP-001~KP-006，其他知识点
    （老师上传的课时、内置课时里没进表的 KP）一律返回 `(0, 0)`。
    旧代码把这两种情况混在同一个 else 分支里，导致那些课时的**每个回答
    都被当成答错**，还会去重复问同一个问题。

    纯函数，不读 state、不读文件 —— 方便单测。
    """
    if total == 0:
        return STATE_NO_RUBRIC
    if hits == 0:
        return STATE_BLANK
    if hits < total:
        return STATE_PARTIAL
    return STATE_CLEAR


# ═══════════════════════════════════════════════════════════════
# 复述阶段问题兜底链：
#   runtime/TMISSION.md 检验问题 → KNOWLEDGE-BASE 检测问题
#   （复述阶段题库 questions.md 已删，不再读阶段题库；
#     探究阶段仍读 stages/deep_inquiry/questions.md）
# ═══════════════════════════════════════════════════════════════

def _read(path: str) -> str:
    try:
        return (ROOT / path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _parse_stage_questions(phase: str) -> list[dict]:
    """第 1 级：stages/<phase>/questions.md 里老师填的问题（剥掉代码块示例，现仅探究阶段用）。"""
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


def _parse_recap_guide() -> dict[str, dict]:
    """读 rules/interaction/RECAP-GUIDE.md 的状态表 → {状态名: {字段: 值}}。

    格式沿用 questions.md 那套 `## 标题` + `- 字段: 值`：

        ## 状态：完全不会
        - 判定: 有证据表但一组都没命中
        - 策略: 降低认知负荷
        - 动作: ...
        - 反馈类型: 提示性

    代码块里的示例会被 `_strip_code_fences` 剥掉（和 `_parse_stage_questions`
    一样），所以文档里可以放心写示例。

    缺 `判定` / `策略` / `动作` 任一个字段的小节会被丢弃 —— 宁可回落到内置
    行为，也不要让半截配置生效。
    """
    text = _read("rules/interaction/RECAP-GUIDE.md")
    if not text:
        return {}
    body = _strip_code_fences(text)
    out: dict[str, dict] = {}
    for block in re.split(r"^##\s*状态[:：]\s*", body, flags=re.M)[1:]:
        lines = block.splitlines()
        name = lines[0].strip() if lines else ""
        if not name:
            continue
        fields: dict[str, str] = {}
        for line in lines[1:]:
            m = re.match(r"-\s*([^\s:：]+)\s*[:：]\s*(.+)", line)
            if m:
                fields[m.group(1).strip()] = m.group(2).strip()
        if all(k in fields for k in ("判定", "策略", "动作")):
            out[name] = fields
    return out


# 按 mtime 失效的缓存。老师改完 RECAP-GUIDE.md，下一轮读取就生效，不用重启进程
# —— 这是刻意避开 `_KP_TITLES` 那个"缓存永不失效"的老坑。
_RECAP_GUIDE_CACHE: dict = {"mtime": None, "data": {}}


def recap_guide() -> dict[str, dict]:
    """带 mtime 失效的 RECAP-GUIDE 状态表。读不到就返回空表（调用方兜底）。"""
    path = ROOT / "rules" / "interaction" / "RECAP-GUIDE.md"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return {}
    if _RECAP_GUIDE_CACHE["mtime"] != mtime:
        _RECAP_GUIDE_CACHE["data"] = _parse_recap_guide()
        _RECAP_GUIDE_CACHE["mtime"] = mtime
    return _RECAP_GUIDE_CACHE["data"]


def _lesson_question_bank(phase: str, lesson_id: str | None) -> list[dict]:
    """上传课时的题库：复述用「检测问题」，探究用四个探究字段。

    只在课时是 store 版（lesson-data/lessons/*.json）时产出。
    """
    if not lesson_id or not is_uploaded_lesson(lesson_id):
        return []
    lesson = load_lesson(lesson_id)
    if not lesson:
        return []
    points = [
        kp for kp in (lesson[0].get("knowledge_points") or []) if kp.get("kp_id")
    ]
    out: list[dict] = []
    if phase == "recap_discussion":
        for kp in points:
            question = str(kp.get("检测问题") or "").strip()
            if question:
                out.append({
                    "kp_id": kp["kp_id"],
                    "question": question,
                    "source": "课时定义 · 检测问题",
                })
    elif phase == "deep_inquiry":
        for kp in points:
            for field, lead in (
                ("为什么这样设计", "为什么"),
                ("如何实现", "如何"),
                ("解决什么实际问题", "用在哪"),
            ):
                value = str(kp.get(field) or "").strip()
                if value:
                    out.append({
                        "kp_id": kp["kp_id"],
                        "question": f"（{lead}）{value}",
                        "source": "课时定义 · 探究字段",
                    })
        if not out:
            # 探究字段没填 → 只对本课知识点用通用兜底，不外借别的课的题目
            out = [{
                "kp_id": kp["kp_id"],
                "question": (
                    f"这个知识点（{kp.get('title') or kp['kp_id']}）能解决什么实际问题？"
                    "结合一个具体场景，说说为什么需要它、它是怎么起作用的。"
                ),
                "source": "课时定义 · 探究字段为空的降级",
            } for kp in points]
    return out


def build_question_queue(
    phase: str, unresolved: list[str], lesson_id: str | None = None
) -> list[dict]:
    """按兜底链为复述/探究阶段组装问题队列。

    上传的课时只走**课时自己的**知识点，**不**回落到
    runtime/TMISSION.md 与 rules/KNOWLEDGE-BASE.md —— 那两处写的是旧课时
    的内容，让上传的课去问别的课的题目就完全跑偏了。
    注意：即便上传的课时没配知识点（题库为空）也不能往下落，
    否则"没填"就等于"改问旧课时的题"。
    """
    if lesson_id and is_uploaded_lesson(lesson_id):
        return _lesson_question_bank(phase, lesson_id)

    if phase == "recap_discussion":
        # 复述阶段不再读阶段题库（questions.md 已删），
        # 问题直接取 TMISSION 检验问题 → KNOWLEDGE-BASE 检测问题。
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
                f"这个知识点（{kp_title(kp, lesson_id)}）能解决什么实际问题？"
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
    question_queue: list[dict]        # 本阶段的问题队列（兜底链产出）
    q_index: int
    attempts: int
    miss_streak: int                  # 复述阶段连续未命中次数（有证据表却没命中才算）
    unresolved_question_notes: list[dict]  # 超过 5 轮的探究问题及后续推导记录
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

# ═══════════════════════════════════════════════════════════════
# 课时库：老师上传的课时定义 + 旧版单课时文件
#
# 两个来源，一套解析：
#   · 新式 —— lesson-data/lessons/<lesson_id>.json，一份文件装下元数据、
#     stages、segments、知识点，由 POST /api/teacher/lesson 写入；
#   · 旧式 —— lesson-data/lesson-plan.json + lesson-data/segments/*.json，
#     只有一节课，刻意保持原样不动。
# ═══════════════════════════════════════════════════════════════

LESSONS_DIR = ROOT / "lesson-data" / "lessons"
LEGACY_PLAN_PATH = ROOT / "lesson-data" / "lesson-plan.json"
SEGMENTS_DIR = ROOT / "lesson-data" / "segments"
LESSON_DATA_DIR = ROOT / "lesson-data"

# lesson_id 会被拼进文件名，必须白名单。只放行字母数字和 . _ -，
# 且首字符是字母数字 —— 拦住 ../、绝对路径、盘符，以及 Windows 保留名
# （CON/NUL/COM1 等不以字母数字开头也过不了这个正则）。
_LESSON_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

# Windows 保留设备名。它们能通过上面的正则（CON、NUL.json 都是"合法"字符），
# 但不能作文件名 —— 带扩展名也不行，`NUL.json` 一样会被当成设备。
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_lesson_id(lesson_id: str) -> str:
    """校验 lesson_id 能安全用作文件名，非法则抛 ValueError。"""
    if not _LESSON_ID_RE.match(lesson_id or ""):
        raise ValueError(
            f"非法 lesson_id：{lesson_id!r}（只允许字母数字与 . _ -，"
            "以字母数字开头，最长 64 字符）"
        )
    if lesson_id.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise ValueError(f"非法 lesson_id：{lesson_id!r}（Windows 保留设备名，不能用作文件名）")
    return lesson_id


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _legacy_plan() -> dict | None:
    return _read_json(LEGACY_PLAN_PATH)


def _scan_lesson_plan_path(lesson_id: str) -> Path | None:
    """扫 lesson-data/<course>/<lesson>/lesson-plan.json（ingest 产出），找 lesson_id 命中那份。"""
    for path in sorted(LESSON_DATA_DIR.glob("*/*/lesson-plan.json")):
        if (_read_json(path) or {}).get("lesson_id") == lesson_id:
            return path
    return None


def is_uploaded_lesson(lesson_id: str) -> bool:
    """是否老师上传的新式课时（区别于旧版单课时文件）。"""
    try:
        safe_lesson_id(lesson_id)
    except ValueError:
        return False
    return (LESSONS_DIR / f"{lesson_id}.json").is_file()


def list_lesson_ids() -> list[str]:
    """全部可用课时 id：老师上传的 + ingest 产出的 lesson-plan + 旧版那一节。"""
    ids: list[str] = []
    if (legacy := _legacy_plan()) and legacy.get("lesson_id"):
        ids.append(legacy["lesson_id"])
    if LESSONS_DIR.is_dir():
        for path in sorted(LESSONS_DIR.glob("*.json")):
            if path.stem not in ids:
                ids.append(path.stem)
    if LESSON_DATA_DIR.is_dir():
        for path in sorted(LESSON_DATA_DIR.glob("*/*/lesson-plan.json")):
            doc = _read_json(path) or {}
            if doc.get("lesson_id") and doc["lesson_id"] not in ids:
                ids.append(doc["lesson_id"])
    return ids


def load_lesson(lesson_id: str) -> tuple[dict, list[dict]] | None:
    """→ (plan, segments)；找不到或格式非法返回 None。

    `plan["segments"]` 在两种来源下都保持「元素至少含 id / minutes」的形状 ——
    编排器只按这两个字段遍历，新式课时的完整段落对象正好也满足。
    完整段落对象单独作为第二个返回值给出。
    """
    if not lesson_id:
        return None
    try:
        safe_lesson_id(lesson_id)
    except ValueError:
        return None

    if is_uploaded_lesson(lesson_id):
        doc = _read_json(LESSONS_DIR / f"{lesson_id}.json")
        if not doc:
            return None
        return doc, list(doc.get("segments") or [])

    # ingest 产出的 per-课时 lesson-plan（lesson-data/<course>/<lesson>/lesson-plan.json）
    if (scanned_path := _scan_lesson_plan_path(lesson_id)) and (
        scanned := _read_json(scanned_path)
    ):
        return scanned, list(scanned.get("segments") or [])

    # 旧版：只认 lesson-plan.json 自己声明的那个 lesson_id
    plan = _legacy_plan()
    if not plan or plan.get("lesson_id") != lesson_id:
        return None
    segments: list[dict] = []
    for item in plan.get("segments") or []:
        seg_id = item.get("id")
        detail = _read_json(SEGMENTS_DIR / f"{seg_id}.json") or {}
        detail.setdefault("segment_id", seg_id)
        detail.setdefault("id", seg_id)
        detail.setdefault("minutes", item.get("minutes"))
        segments.append(detail)
    return plan, segments


def save_lesson(doc: dict) -> str:
    """原子落盘一份课时定义，返回相对路径。

    先写 `.tmp` 再 `os.replace` —— 校验过 `_lesson_plan` 会抛 503 读端，
    不能让它们读到写了一半的 JSON。写路径集中在这里，读端一律走
    `load_lesson`，这样 LESSONS_DIR 只有一个引用点（测试也好打桩）。
    """
    lesson_id = safe_lesson_id(str(doc.get("lesson_id") or ""))
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    path = LESSONS_DIR / f"{lesson_id}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return f"lesson-data/lessons/{lesson_id}.json"


def lesson_source_label(lesson_id: str) -> str:
    """给接口返回用：这节课的定义存在哪。"""
    if is_uploaded_lesson(lesson_id):
        return f"lesson-data/lessons/{lesson_id}.json"
    if (path := _scan_lesson_plan_path(lesson_id)):
        return str(path.relative_to(ROOT)).replace("\\", "/")
    if (plan := _legacy_plan()) and plan.get("lesson_id") == lesson_id:
        return "lesson-data/lesson-plan.json（旧版单课时）"
    return "未找到"


_KP_EXTRA_FIELDS = (
    "定义", "检测问题", "掌握表现",
    "为什么这样设计", "如何实现", "解决什么实际问题", "关联学科",
)


def format_knowledge_point(kp: dict) -> str:
    """把一个知识点渲染成进提示词的文本块（字段序与 KNOWLEDGE-BASE.md 一致）。"""
    head = f"{kp.get('kp_id', '')} {kp.get('title', '')}".strip() or "知识点"
    lines = [f"## {head}"]
    for field in _KP_EXTRA_FIELDS:
        value = str(kp.get(field) or "").strip()
        if value:
            lines.append(f"- {field}: {value}")
    return "\n".join(lines)


def lesson_knowledge_block(lesson_id: str) -> str:
    """本课知识点区块；没有（旧版课时）则返回空串。

    先做 `is_uploaded_lesson` 短路，别直接 load_lesson —— 这个函数
    **每轮都要调**，旧式课时走 load_lesson 会把整份 plan 加六个段落文件
    全读一遍，只为了返回空串。
    """
    if not lesson_id or not is_uploaded_lesson(lesson_id):
        return ""
    lesson = load_lesson(lesson_id)
    if not lesson:
        return ""
    points = lesson[0].get("knowledge_points") or []
    if not points:
        return ""
    return "\n\n".join(format_knowledge_point(kp) for kp in points)


def load_plan(state: ClassroomState) -> dict:
    """载入并校验课程计划（规范第 9 节校验清单）。仅首轮生效，之后幂等。"""
    if state.get("host_phase") != "uninitialized":
        return {}

    lesson_id = state.get("lesson_id") or ""
    lesson = load_lesson(lesson_id)
    if lesson is None:
        # student_status 必须一起置 ended —— 会话层靠 host_phase=="ending" 且
        # student_status=="ended" 才把 lesson_status 落成 ended；少了它，这一节
        # 会卡在 running，心跳线程永远在跑。
        return {
            "host_phase": "ending",
            "student_status": "ended",
            "reply_text": f"开课失败：找不到课时 {lesson_id!r}",
            "advance_reason": "课时不存在",
        }
    plan, _segments = lesson

    # 启动校验（任一失败 → 拒绝开课）
    problems = validate_plan(plan, uploaded=is_uploaded_lesson(lesson_id))
    if problems:
        return {
            "host_phase": "ending",
            "student_status": "ended",
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
        "miss_streak": 0,
        "unresolved_question_notes": [],
    }


def validate_plan(plan: dict, *, uploaded: bool = False) -> list[str]:
    problems: list[str] = []
    if plan.get("total_minutes", 0) <= 0:
        problems.append("total_minutes 必须大于 0")
    enabled = [s for s in plan.get("stages", []) if s.get("enabled")]
    if not enabled:
        problems.append("至少要启用一个阶段")
    if sum(s.get("minutes", 0) for s in enabled) > plan.get("total_minutes", 0):
        problems.append("启用阶段的时长之和超过 total_minutes")
    for s in enabled:
        stage_id = s.get("id")
        if not stage_id:
            problems.append("阶段缺 id")
        elif stage_id not in STAGE_NAMES:
            problems.append(
                f"未知阶段 id：{stage_id!r}（可用：{'、'.join(STAGE_NAMES)}）"
            )
        if s.get("advance_when") not in ("either", "evidence", "budget"):
            problems.append(f"阶段 {stage_id} 的 advance_when 非法")
        if stage_id in ("recap_discussion", "deep_inquiry", "class_discussion"):
            if not (ROOT / "stages" / stage_id).is_dir():
                problems.append(f"启用阶段 {stage_id} 缺 stages/ 目录")
    # advance_policy 的四个键在开课时被 load_plan 直接下标取用，
    # 少一个就是开课 KeyError —— 所以校验必须把它拦在写盘之前。
    policy = plan.get("advance_policy")
    if not isinstance(policy, dict):
        problems.append("缺 advance_policy")
    else:
        for key in ("on_budget_exhausted", "on_evidence_reached",
                    "min_stage_minutes", "max_stage_overrun_minutes"):
            if key not in policy:
                problems.append(f"advance_policy 缺 {key}")
    segments = plan.get("segments", [])
    if uploaded:
        # 上传的课时把段落内联在同一个文件里，所以不查磁盘上的段落文件。
        if not segments:
            problems.append("segments 不能为空")
        seen_seg: set[str] = set()
        for i, seg in enumerate(segments):
            seg_id = seg.get("id")
            if not seg_id:
                problems.append(f"第 {i + 1} 个段落缺 id")
            elif seg_id in seen_seg:
                problems.append(f"段落 id 重复：{seg_id}")
            else:
                seen_seg.add(seg_id)
        declared: set[str] = set()
        for kp in plan.get("knowledge_points") or []:
            kp_id = kp.get("kp_id")
            if not kp_id:
                problems.append("有知识点缺 kp_id")
            elif kp_id in declared:
                problems.append(f"知识点 id 重复：{kp_id}")
            else:
                declared.add(kp_id)
        # 段落挂到不存在的知识点上，会让未声明的 kp_id 进学生的掌握档案
        for seg in segments:
            for kp_id in seg.get("knowledge_point_ids") or []:
                if declared and kp_id not in declared:
                    problems.append(f"段落 {seg.get('id')} 引用了未声明的知识点 {kp_id}")
    else:
        for seg in segments:
            seg_id = seg.get("id")
            if not seg_id:
                problems.append("有段落缺 id")
            elif not (SEGMENTS_DIR / f"{seg_id}.json").is_file():
                problems.append(f"缺段落文件 {seg_id}.json")
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


def _current_segment_text(state: ClassroomState) -> str:
    """当前段落的原文。旧式课时散在 lesson-data/segments/，新式内联在课时文件里。"""
    seg_id = state.get("active_segment_id")
    if not seg_id:
        return ""
    lesson_id = state.get("lesson_id") or ""
    if not is_uploaded_lesson(lesson_id):
        return _read(f"lesson-data/segments/{seg_id}.json")
    lesson = load_lesson(lesson_id)
    for seg in (lesson[1] if lesson else []):
        if seg.get("id") == seg_id or seg.get("segment_id") == seg_id:
            return json.dumps(seg, ensure_ascii=False, indent=2)
    return ""


def load_context(state: ClassroomState) -> dict:
    """分层装配上下文（规范第 4 节）。空壳阶段注入占位提示，不报错；
    进入复述/探究阶段时按兜底链组装问题队列。"""
    phase = state.get("host_phase")
    parts: list[str] = []

    # 规则层：KNOWLEDGE-BASE.md 是**旧课时**的知识点目录。上传的课时有自己的
    # [本课知识点]，再塞一份别的课的知识点进上下文只会互相干扰（这个仓库有过
    # 模型在讲解课上编出无关概念的记录，见下面 anchor 那段注释）。
    if not is_uploaded_lesson(state.get("lesson_id") or ""):
        parts.append("[知识库]\n" + _read("rules/KNOWLEDGE-BASE.md"))
    # 课时层：老师经 POST /api/teacher/lesson 传入的知识点。
    # 每轮从磁盘读而不是塞进 session state —— session state 会被
    # `s["state"] = st` 整体替换，挂在外面的字段容易丢；而且 load_context
    # 本来每轮就 _read 一遍，行为一致。旧式课时没有这段，返回空串。
    if kp_block := lesson_knowledge_block(state.get("lesson_id") or ""):
        parts.append("[本课知识点]\n" + kp_block)
    # 计划层（仅当前阶段配置）
    plan = state.get("lesson_plan") or {}
    for s in plan.get("stages", []):
        if s["id"] == phase:
            parts.append(f"[阶段计划] {s}")
    # 课堂层：当前 segment + 绑定的 KP 全文
    if state.get("active_segment_id"):
        seg_text = _current_segment_text(state)
        if seg_text:
            parts.append("[当前段落]\n" + seg_text)
    # 阶段层（只有复述/探究/讨论三幕有；空壳 → 占位提示）
    # 复述阶段只读 prompt.md（questions.md / rubric.md 已删）；
    # 探究 / 讨论阶段仍读 questions.md + prompt.md + rubric.md。
    if phase in ("recap_discussion", "deep_inquiry", "class_discussion"):
        stage_files = (
            ("prompt.md",)
            if phase == "recap_discussion"
            else ("questions.md", "prompt.md", "rubric.md")
        )
        for f in stage_files:
            text = _read(f"stages/{phase}/{f}")
            parts.append(f"[{f}]\n" + (text.strip() or "[本阶段内容未配置]"))
    # 档案层
    parts.append("[掌握档案]\n" + json.dumps(state.get("kp_stars", {}), ensure_ascii=False))

    updates: dict = {"assembled_prompt": "\n\n".join(parts)}

    # 进入提问阶段 → 组装问题队列 + 未关闭目标
    if phase in ("recap_discussion", "deep_inquiry") and not state.get("question_queue"):
        queue = build_question_queue(
            phase, state.get("unresolved") or [], state.get("lesson_id")
        )
        updates["question_queue"] = queue
        updates["q_index"] = 0
        updates["unresolved"] = [q["kp_id"] for q in queue]
    elif phase == "guided_learning" and not state.get("unresolved"):
        # 讲解阶段的"未关闭目标" = 全部段落涉及的 KP（讲过 ≠ 关闭）
        lesson = load_lesson(state.get("lesson_id") or "")
        kps: list[str] = []
        for seg in (lesson[1] if lesson else []):
            kps.extend(seg.get("knowledge_point_ids", []))
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


def _segment_detail(plan: dict, seg_id: str | None) -> dict | None:
    """按 id 取段落详情。旧式课时散在 lesson-data/segments/，新式内联在课时文件里。"""
    if not seg_id:
        return None
    lesson_id = plan.get("lesson_id") or ""
    if not is_uploaded_lesson(lesson_id):
        return _read_json(SEGMENTS_DIR / f"{seg_id}.json")
    lesson = load_lesson(lesson_id)
    for seg in (lesson[1] if lesson else []):
        if seg.get("id") == seg_id or seg.get("segment_id") == seg_id:
            return seg
    return None


def _segment_at(plan: dict, cursor: int) -> dict | None:
    """按游标取段落详情。"""
    segs = _segments(plan)
    if cursor < 0 or cursor >= len(segs):
        return None
    return _segment_detail(plan, segs[cursor].get("id"))


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
    return _segment_detail(plan, seg_id)


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
    # 备课材料：load_context 每轮装配的 [知识库]/[本课知识点]/[当前段落]/[掌握档案]…
    # 接上它是为了让模型把话说准（尤其老师上传的知识点），不是让它改讲什么 ——
    # 讲什么、问什么仍由 directive 决定。所以人设里明确"只当参考、不要照读"。
    background = (state.get("assembled_prompt") or "").strip()
    return llm_chat(
        "你是一名课堂智能体，正在给学生上课。"
        "以【本轮指令】为教学目标和流程边界，但不要逐字复述指令或把它说成生硬的话术。"
        "在不改变本轮教学动作、不擅自改变课堂流程的前提下，可以自然回应学生刚才的表达，并用必要的承接语让对话连贯。"
        "只有确实有助于完成本轮目标时才追问；遵守指令要求的问题数量，不额外堆叠问题。"
        "【课堂背景】仅用于理解课程和学生情况，不要照读或提及背景材料。"
        "要求：中文口语，通常1-3句；需要解释时可适当展开。表达具体、友好、自然，不写标题、不用 Markdown、不加括号注释。",
        (f"【课堂背景】\n{background}\n\n" if background else "")
        + f"当前阶段：{STAGE_NAMES.get(phase, phase)}（已进行 {elapsed:.0f}/{budget:.0f} 分钟）\n"
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
                    if cur
                    # 不写死课名：上传的课时走到这里会拿到别的课的内容
                    else f"本课（{plan.get('lesson_title') or '本节课'}）已讲过的内容"
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
        hold_recap_question = False
        hold_deep_question = False

        if pending and msg.strip():
            # 学生回答了上一轮挂起的问题 → 反馈
            kp = pending["kp_id"]
            hits, total = match_evidence(kp, msg)
            updates["current_target"] = kp

            if phase == "recap_discussion":
                # ── 复述阶段：状态驱动 ──────────────────────────────
                # 状态 → 策略查 rules/interaction/RECAP-GUIDE.md（老师可改，不用动代码）。
                # 表里查不到就回落到下面的内置措辞，行为不会比原来差。
                state_name = judge_state(hits, total)
                guide = recap_guide().get(state_name) or {}
                action = guide.get("动作") or ""

                # 连续未命中：只在「有证据表但一组都没命中」时累加。
                # 没有证据表不算失败 —— 那是这道题没有评定标准，不是学生的错。
                streak = state.get("miss_streak", 0)
                if total and hits == 0:
                    streak += 1
                elif hits:
                    streak = 0
                updates["miss_streak"] = streak

                if state_name == STATE_NO_RUBRIC:
                    # 没有证据表：不下判定。措辞上也不能像在否定学生 ——
                    # 旧的 else 分支把这种情况和"答错了"混在一起，会一直说"再想想"。
                    lines.append("嗯，我们换个角度说说看。")
                    dl.append(action or "按通用方式追问一层，别用否定的措辞。")
                elif state_name == STATE_CLEAR:
                    lines.append("很好，说得很完整！")
                    dl.append(f"学生刚才答得完整。{action}")
                    updates["attempts"] = 0
                elif state_name == STATE_PARTIAL:
                    attempt = state.get("attempts", 0) + 1
                    updates["attempts"] = attempt
                    hold_recap_question = True
                    scaffold = _recap_scaffold(kp, attempt, partial=True)
                    lines.append(scaffold)
                    dl.append(
                        f"学生已经答出一部分，先肯定已说对的内容。当前是第 {attempt} 次引导。"
                        f"{action}\n{scaffold}\n只围绕当前题的这个小步骤继续引导，不要提出队列中的下一题。"
                    )
                else:                                   # STATE_BLANK
                    attempt = state.get("attempts", 0) + 1
                    updates["attempts"] = attempt
                    hold_recap_question = True
                    scaffold = _recap_scaffold(kp, attempt, partial=False)
                    lines.append(scaffold)
                    dl.append(
                        f"学生暂时没答出来。当前是第 {attempt} 次引导。{action}\n{scaffold}\n"
                        "一次只引导当前这个小步骤，并请学生尝试回答；不要公布队列中的下一题，也不要把对话直接推进到下一题。"
                    )
            else:
                # ── 深层探究：记录超过 5 轮仍在讨论的问题，但继续保留当前题，
                # 通过递进脚手架帮助学生自己推导，不自动公布答案或切幕。 ──
                attempt = state.get("attempts", 0) + 1
                resolved = (bool(total) and hits == total) or _deep_answer_has_depth(msg)
                notes = [dict(item) for item in (state.get("unresolved_question_notes") or [])]
                tracked_note = next((
                    item for item in reversed(notes)
                    if item.get("phase") == phase
                    and item.get("kp_id") == kp
                    and item.get("question") == pending["question"]
                    and item.get("status") == "继续引导中"
                ), None)
                if attempt > MAX_DEEP_INQUIRY_ATTEMPTS and tracked_note is None:
                    tracked_note = {
                        "phase": phase,
                        "kp_id": kp,
                        "question": pending["question"],
                        "attempts": attempt,
                        "status": "继续引导中",
                        "note": "对话超过 5 轮，已记录并继续用递进提示引导",
                        "recorded_at": state.get("now"),
                    }
                    notes.append(tracked_note)
                elif tracked_note is not None:
                    tracked_note["attempts"] = attempt

                if tracked_note is not None and resolved:
                    tracked_note["status"] = "已由学生推导"
                    tracked_note["student_solution"] = msg
                    tracked_note["resolved_at"] = state.get("now")
                    tracked_note["note"] = "超过 5 轮后继续引导，学生已自行推导"
                if len(notes) != len(state.get("unresolved_question_notes") or []) or tracked_note is not None:
                    updates["unresolved_question_notes"] = notes

                if resolved and attempt >= 2:
                    if total and hits == total:
                        lines.append("你已经把这个想法展开了，我们带着这个结论继续看下一题。")
                        dl.append("简短肯定学生的推理或例子，过渡到队列中的下一题。")
                    else:
                        lines.append("你的解释已经说清了关键原因，我们继续看下一题。")
                        dl.append("简短肯定学生的推理，过渡到队列中的下一题。")
                    updates["attempts"] = 0
                else:
                    updates["attempts"] = attempt
                    hold_deep_question = True
                    if _is_nonanswer(msg):
                        scaffold = _deep_inquiry_scaffold(kp, pending["question"], attempt)
                        if tracked_note is not None and attempt == MAX_DEEP_INQUIRY_ATTEMPTS + 1:
                            lines.append("这道题我已经记下来了，我们继续拆小一步，一起把思路推出来。\n" + scaffold)
                        else:
                            lines.append(scaffold)
                        dl.append(
                            f"学生暂时没有给出实质回答（当前第 {attempt} 次回应）。{scaffold}\n"
                            "若已超过 5 次，问题已记录；继续留在当前题，用一个更细的小问题帮助学生自己推导。不要公布完整答案、不要提出队列中的下一题，也不要切换环节。"
                        )
                    else:
                        lines.append("我们再沿着这个问题往下想一步。" + ("这道题我已经记下来了。" if tracked_note is not None and attempt == MAX_DEEP_INQUIRY_ATTEMPTS + 1 else ""))
                        dl.append(
                            f"学生的观点是：{msg}\n先回应其中一个具体点，再围绕原因、依据或例子追问一个小问题。"
                            f"当前是第 {attempt} 次回应。当前问题还未解决，继续留在本题；若已超过 5 次，问题已记录。不要公布完整答案、提出下一题或切换环节。"
                        )
            if wrap:
                # 预算耗尽收尾：不再抛下一问，留给下一幕/下节课
                updates["pending_question"] = None
                lines.append("时间到了，这个问题我们先收在这里。")
                dl.append("本阶段时间到了，简短收尾。**绝对不要再提新问题**。")
            elif hold_recap_question or hold_deep_question:
                # 当前题仍在引导中：保留题目及索引，下一轮继续同一道题。
                updates["pending_question"] = pending
                updates["q_index"] = idx
                updates["current_question"] = pending["question"]
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
            if not wrap:
                updates["current_question"] = (updates.get("pending_question") or pending).get("question")
        elif pending:
            # 心跳没有新的学生回答时，不得把它计作一次尝试或推进题目。
            updates["pending_question"] = pending
            updates["current_question"] = pending["question"]
            updates["current_target"] = pending["kp_id"]
            speak = False
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
        detail = "、".join(
            f"{kp_title(kp, state.get('lesson_id'))} {s} 星"
            for kp, s in sorted(stars.items())
        )
        weak = [
            kp_title(kp, state.get("lesson_id"))
            for kp, s in sorted(stars.items()) if s <= 2
        ]
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
    if not speak:
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


def _recap_scaffold(kp_id: str, attempt: int, partial: bool) -> str:
    """复述阶段逐级增加支架；未达证据标准前保持当前题，不抛出下一题。"""
    if kp_id == "KP-002":
        if partial:
            if attempt <= 1:
                return "你已经抓住了其中一个环节。另一个环节是谁负责？可以按“作业进入内存”和“就绪进程获得 CPU”这两步来想。"
            if attempt == 2:
                return "作业调入内存由高级调度负责；就绪进程获得 CPU 由低级调度负责。课程还提到中级调度通过对换来做内存平衡。你试着把这三者的分工说清楚。"
            return "完整地说，外存作业调入内存是高级调度（作业调度），就绪进程被选上 CPU 是低级调度（进程调度），中级调度负责对换和内存平衡。请你用自己的话把三者分工说一遍。"
        if attempt <= 1:
            return "我们拆成两步。先看第一步：外存中的作业被调入内存，这一步属于哪一级调度？"
        if attempt == 2:
            return "第一步叫高级调度（也叫作业调度）。接着看第二步：内存中的就绪进程由哪一级调度选上 CPU？"
        return "我把相关分工连起来：高级调度（作业调度）把作业调入内存，低级调度（进程调度）从就绪队列选择进程上 CPU；中级调度通过对换做内存平衡。你试着用自己的话说清这三者的分工。"
    if kp_id == "KP-004":
        if attempt <= 1:
            return "先只看 SJF：如果短作业不断到来，长作业可能会遇到什么情况？"
        if attempt == 2:
            return "长作业可能一直排不上，形成饥饿。再看 HRRN：等待时间变长，会怎样影响它的响应比或优先级？"
        return "关键是两点：SJF 可能让长作业长期得不到服务；HRRN 把等待时间计入响应比，让等得久的作业优先级逐渐提高。请你用自己的话说说这层关系。"
    if kp_id == "KP-003":
        if attempt <= 1:
            return "先从“周转时间”开始：它从作业提交开始，算到哪个时刻结束？"
        if attempt == 2:
            return "周转时间到作业完成为止。再看等待时间和响应时间：一个关注在就绪队列里等了多久，另一个关注首次获得 CPU 的时刻。你试着分别说清它们。"
        return "可以按三个终点记：提交到完成是周转时间；在就绪队列中的等待是等待时间；提交到第一次获得 CPU 是响应时间。请你对照这三个终点复述一遍。"
    if kp_id == "KP-005":
        if attempt <= 1:
            return "先抓住判断标准：A 正在运行时，B 到来后，A 会不会立刻被打断？这取决于调度方式是否允许什么操作？"
        if attempt == 2:
            return "允许打断当前运行进程就叫抢占。再想一个触发条件：时间片用完或更高优先级进程到来时，系统会怎么做？"
        return "要看当前进程能否被打断：能被打断是抢占式；不能打断、等它主动结束或阻塞再切换，是非抢占式。你用 A、B 的例子判断一下。"
    if kp_id == "KP-006":
        if attempt <= 1:
            return "先从 RR 想起：轮到一个进程运行时，它最多能连续使用 CPU 多久？"
        if attempt == 2:
            return "RR 使用时间片，时间片用完就切换。再看多级反馈队列：进程会根据运行表现发生什么变化？"
        return "RR 通过时间片轮转提高响应性；多级反馈队列会根据进程行为在队列间调整位置，不需要预先知道运行时间。请你概括这两个特点。"

    hint = _hint(kp_id)
    if attempt <= 1:
        return (f"你已经说到一部分了。我们先聚焦缺的关键点：{hint}"
                if partial else f"我们先拆小一步：{hint} 先说说其中一个关键词是什么意思。")
    if attempt == 2:
        return (f"再用一个小例子帮助你补全：{hint} 你试着把缺的部分说出来。"
                if partial else f"先抓住一个关键点：{hint} 你能试着举个相关的小例子吗？")
    return (f"我把缺的关键点解释清楚：{hint} 请你把完整思路用自己的话复述一遍。"
            if partial else f"我先结合刚才的课程内容把这个概念解释清楚：{hint} 然后请你用自己的话复述关键点。")


def _is_nonanswer(text: str) -> bool:
    """识别空输入、明确卡住或请求提示；不把开放式的非标准答案判成答错。"""
    normalized = re.sub(r"[\s，。！？、,.!?；;：:‘’“”\"'…]+", "", str(text or ""))
    if not normalized:
        return True
    exact = {
        "不知道", "我不知道", "真的不知道", "不太知道", "不清楚", "我不清楚",
        "不会", "我不会", "没想法", "没有想法", "没思路", "没有思路",
        "答不上来", "不知道怎么说", "我不知道怎么说", "能给个提示吗",
        "给点提示", "提示一下", "帮我提示一下", "不懂", "我不懂",
    }
    return normalized in exact or (
        len(normalized) <= 10
        and normalized.endswith(("不知道", "不清楚", "不会", "没思路", "没有思路", "答不上来", "不懂"))
    )


def _deep_answer_has_depth(text: str) -> bool:
    """识别开放回答中的最低限度推理/举例证据，避免只用关键词误判探究题。"""
    content = re.sub(r"\s+", "", str(text or ""))
    links = ("因为", "所以", "由于", "导致", "如果", "例如", "比如", "举例", "相比", "从而", "这样会", "为了")
    return len(content) >= 18 and any(link in content for link in links)


def _deep_inquiry_scaffold(kp_id: str, question: str, attempt: int) -> str:
    """探究阶段的渐进式提示：逐层缩小问题，不直接代替学生得出结论。"""
    if kp_id == "KP-004":
        if attempt <= 1:
            return "先从一个具体情形想：如果短作业不断到来，队列里的长作业会发生什么？"
        if attempt == 2:
            return "如果这种情况持续，长作业最担心的是什么？试着用一个词描述它一直等不到服务的状态。"
        if attempt == 3:
            return "HRRN 的响应比可以写成（等待时间＋服务时间）/服务时间。先不急着下结论：等待时间变大时，分子会怎样变化？"
        if attempt == 4:
            return "我们代入两个数试试：甲已等 8 个单位、还需运行 2 个单位；乙刚等 1 个单位、也需运行 2 个单位。分别按公式算响应比，哪个更高？"
        if attempt % 2:
            return "把刚才算出的响应比和 SJF 只看运行时间的规则对照一下：HRRN 多考虑了哪个因素？这个因素怎样影响长时间等待的作业？"
        return "再换个角度：如果作业每多等一会儿，它在公式中的哪个量会变化？你预测这个变化会让它更容易还是更难被选中？"
    if kp_id == "KP-002":
        if attempt <= 1:
            return "先把它放进一个生活场景：如果你在奶茶店排队，哪种叫号方式会让人觉得更快？"
        if attempt == 2:
            return "假设一位顾客先来但订单复杂，后来的人只买一件。你会先服务谁？说说你最想优先保障什么。"
        if attempt == 3:
            return "如果总是优先处理简单订单，最早来的复杂订单可能会怎样？你会用什么办法避免它一直等？"
        if attempt % 2:
            return "把你提出的规则放到另一种场景里：如果同时有很多短任务和一个长任务，哪一方会受影响？"
        return "请试着只改变一个条件：如果等待时间越长越应该被照顾，你会怎么修改刚才的叫号规则？"
    if kp_id == "KP-005":
        if attempt <= 1:
            return "先观察 A 正在运行、B 刚到达这个场景：什么条件下操作系统有理由打断 A？"
        if attempt == 2:
            return "再想一个具体触发事件：时间片用完或 B 更紧急时，系统可能采取什么动作？"
        if attempt == 3:
            return "如果系统一直不打断 A，B 可能要等多久？如果频繁打断，又会付出什么代价？"
        if attempt % 2:
            return "假设 A 只差一点就完成，而 B 是交互任务刚到达。你会考虑哪些因素来决定是否切换？"
        return "换一种情况：如果 B 是紧急任务，和 B 只是普通后台任务相比，你会怎样调整是否打断 A 的判断？为什么？"
    if kp_id == "KP-003":
        if attempt <= 1:
            return "先想这三个指标分别想回答什么问题：任务总共花多久、排队等多久、多久能第一次得到响应？"
        if attempt == 2:
            return "拿一个作业举例：提交、进入就绪队列、第一次拿到 CPU、最终完成。你会怎样用这些时刻区分三个指标？"
        if attempt == 3:
            return "设作业 0 分钟提交、3 分钟首次拿到 CPU、10 分钟完成，中间在就绪队列等了 5 分钟。你先分别指出三个指标的起止时刻。"
        if attempt % 2:
            return "如果只看总完成时间，能不能看出用户是否很快得到第一次反馈？你用刚才的时间线解释一下。"
        return "再假设两个作业完成时间相同，但一个很早就首次获得 CPU。你觉得哪个指标能体现这个差异？"
    if kp_id == "KP-006":
        if attempt <= 1:
            return "先想象一个交互系统：用户点击后，为什么希望每个进程都能较快轮到 CPU？"
        if attempt == 2:
            return "如果一个进程一直占着 CPU，其他进程会遇到什么？你会怎样限制它连续运行的时间？"
        if attempt == 3:
            return "如果每个进程用完一小段时间就暂时让出 CPU，交互体验会怎样变化？这种切换有没有代价？"
        if attempt % 2:
            return "有的进程常常很快让出 CPU，有的会一直用满时间片。系统能否根据这种行为调整它们后续获得 CPU 的机会？你会怎么设计？"
        return "如果系统事先不知道任务长短，但能观察它每次是否用满时间片，你会如何利用这个信息安排之后的队列？"
    if attempt <= 1:
        return f"先从题目里的一个具体情形开始想：{question} 你觉得这里最先发生了什么？"
    if attempt == 2:
        return "再往下一步看它背后的原因或机制：什么条件导致了这个结果？可以用一个例子说明。"
    if attempt % 2:
        return f"换一个更小的场景想想：{question} 哪个条件变化会让结果不同？"
    return f"试着反过来推：如果你认为的原因不存在，结果会有什么不同？题目是“{question}”，说说你的推理过程。"


def _hint(kp_id: str) -> str:
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
        if seg_id:
            seg = _segment_detail(state.get("lesson_plan") or {}, seg_id)
            if seg:
                for kp in seg.get("knowledge_point_ids", []):
                    bump(kp, 1, "dialogue", f"讲解阶段讲过（{seg.get('title', '')}）")

    elif phase in ("recap_discussion", "deep_inquiry"):
        kp = state.get("current_target")
        if kp:
            hits, total = match_evidence(kp, msg)
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
            "unresolved_question_notes": state.get("unresolved_question_notes") or [],
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
        "miss_streak": 0,
        "unresolved_question_notes": state.get("unresolved_question_notes") or [],
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
        queue = build_question_queue(nxt, carried, state.get("lesson_id"))
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
    detail = "、".join(
        f"{kp_title(kp, state.get('lesson_id'))} {v} 星"
        for kp, v in sorted(stars.items())
    )
    weak = [
        kp_title(kp, state.get("lesson_id"))
        for kp, v in sorted(stars.items()) if v <= 2
    ]
    polished = llm_chat(
        "你是一名课堂智能体，正在宣布下课。",
        f"本课知识点掌握情况：{detail or '（本课没有采集到证据）'}\n"
        + (f"还没掌握好的：{'、'.join(weak)}。\n" if weak else "全部达到理解线以上。\n")
        + "要求：中文口语，3-5 句。先回顾本课学了什么，再点出课后该补的地方，"
          "最后说下节课见。不要用 Markdown、不要罗列编号。",
    )
    return (polished.strip(), True) if polished else (plain, False)


def _ending_summary(state: ClassroomState, pending_snapshot: dict | None = None) -> str:
    stars = state.get("kp_stars") or {}
    snaps = list(state.get("stage_snapshots") or [])
    if pending_snapshot:
        snaps = snaps + [pending_snapshot]
    lines = ["[下课总结]"]
    lines.append(
        f"本课计划 {state.get('lesson_plan', {}).get('total_minutes')} 分钟，"
        f"实际上了 {state.get('lesson_elapsed_minutes')} 分钟，"
        f"共 {len(snaps)} 幕。"
    )
    if stars:
        lines.append("掌握情况：")
        for kp, st in sorted(stars.items()):
            lines.append(f"  - {kp}：{'★' * st}（{STAR_STATUS.get(st, '未检测')}）")
    open_kps = [k for k, st in stars.items() if st < 3]
    if open_kps:
        lines.append(f"建议课后补一补：{('、'.join(open_kps))}。")
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
    question_notes = "\n".join(
        f"- [{note.get('phase')}] {note.get('question')}（状态：{note.get('status', '继续引导中')}；{note.get('note')}；学生推导：{note.get('student_solution', '尚未推导出来')}）"
        for note in (state.get("unresolved_question_notes") or [])
    ) or "（无）"
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

### 已记录的探究问题
{question_notes}

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
    notes = data.setdefault("unresolved_question_notes", [])
    existing_notes = {
        (item.get("phase"), item.get("kp_id"), item.get("question"), item.get("recorded_at")): item
        for item in notes if isinstance(item, dict)
    }
    for item in state.get("unresolved_question_notes") or []:
        key = (item.get("phase"), item.get("kp_id"), item.get("question"), item.get("recorded_at"))
        if key in existing_notes:
            existing_notes[key].update(item)
        else:
            notes.append(item)
            existing_notes[key] = item
    data["messages"].append({
        "turn_at": state.get("now"),
        "phase": state.get("host_phase"),
        "speaker": state.get("speaker"),
        "current_question": state.get("current_question"),
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
        "miss_streak": 0,
        "unresolved_question_notes": [],
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
