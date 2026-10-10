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
    星级评定由下课前的 LLM 依据整课对话综合判定（见 _assess_mastery_with_llm）；
    复述/探究阶段「答没答上」的推进/留守也交给 LLM 判定，不再写死关键词表。

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
EVENT_END_LESSON = "end_lesson"  # 老师按"结束本节课"，直接下课（跳过剩余阶段）


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

try:
    from llm_override import llm_params
except ImportError:  # 作为 orchestrator 包导入时
    from .llm_override import llm_params


def llm_available() -> bool:
    base, key, model = llm_params()
    return bool(base and key and model)


# 诊断计数：实测时用，能立刻看出"到底调没调成功"
LLM_DIAG: dict = {"calls": 0, "ok": 0, "failed": 0, "last_error": None}

# 未接入 LLM 时不再用写死的模板假装上课，而是明确告知当前无法对话。
NO_LLM_NOTICE = "当前没有接入 AI 模型，无法进行对话。请先在平台的模型设置里配置好模型后再试。"


def llm_chat(system: str, user: str) -> str | None:
    """调 OpenAI 兼容端点。失败时**不静默**——写诊断并打日志。

    返回 None 时调用方走确定性降级脚本，但 last_error 会保留原因，
    否则实测时分不清"没接上"和"接上了但走了兜底"。
    """
    base, key, model = llm_params()
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


_KP_TITLES: dict[str, str] | None = None


# 平台课程知识点标题注册表：load_plan_for_session 建计划时写入。
_PLAN_KP_TITLES: dict[str, str] = {}


def register_kp_titles(titles: dict[str, str] | None) -> None:
    """注册平台下发的知识点标题，供 kp_title 免查本地课时直接使用。"""
    for kp_id, title in (titles or {}).items():
        if kp_id and title:
            _PLAN_KP_TITLES[str(kp_id)] = str(title)


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

    # 平台课程的知识点标题由集成层建计划时注册（course_adapter），
    # 查得到就绝不说 KP-xxx 这类内部编号。
    registered = _PLAN_KP_TITLES.get(kp_id)
    if registered:
        return registered

    global _KP_TITLES
    if _KP_TITLES is None:
        _KP_TITLES = {}
        text = _read("rules/KNOWLEDGE-BASE.md")
        for m in re.finditer(r"^##\s+(KP-\d+)\s+(.+)$", text or "", re.M):
            _KP_TITLES[m.group(1)] = m.group(2).strip()
    return _KP_TITLES.get(kp_id, kp_id)


MAX_DEEP_INQUIRY_ATTEMPTS = 5


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
    phase: str,
    unresolved: list[str],
    lesson_id: str | None = None,
    plan: dict | None = None,
) -> list[dict]:
    """按兜底链为复述/探究阶段组装问题队列。

    平台链路优先：会话带 learning_context（plan 的 source 为
    platform-published）时，题目由已发布知识点包提供（prompt_context）。
    非平台计划时该分支返回空，自然落到下面的本地兜底链。

    上传的课时只走**课时自己的**知识点，**不**回落到
    runtime/TMISSION.md 与 rules/KNOWLEDGE-BASE.md —— 那两处写的是旧课时
    的内容，让上传的课去问别的课的题目就完全跑偏了。
    注意：即便上传的课时没配知识点（题库为空）也不能往下落，
    否则"没填"就等于"改问旧课时的题"。
    """
    from apps.integration import prompt_context

    if prompt_context.is_platform_plan(plan or {}):
        return prompt_context.question_queue(phase, plan, unresolved, generate=llm_chat)

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
        kps = list(dict.fromkeys(unresolved))
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

    # ── 平台上下文 ──
    # ⚠️ LangGraph 只保留本 TypedDict 声明过的键。这两个字段必须在这里声明，
    # 否则即便会话层把它们塞进 state，图节点（load_plan / load_context /
    # judge_mastery / llm_polish / _hint）也读不到，平台发布会静默退化成
    # 「课时不存在」。会话层 _step 每轮显式回注也依赖这条声明。
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
    #   end_lesson   —— 老师按"结束本节课"，直接下课（跳过剩余阶段）
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
    kp_stars: dict[str, int]          # 运行中的星级（平台会话由会话层写 student.knowledge_mastery）
    kp_meta: dict[str, dict]          # 各 KP 的 last_source/stage/evidence
    stage_snapshots: Annotated[list[dict], operator.add]
    dialogue_log: Annotated[list[dict], operator.add]  # 整课对话记录 [{"role": student/ai, "text"}]
                                                        # 供下课前的 LLM 掌握度评定使用

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
    """载入并校验课程计划（规范第 9 节校验清单）。仅首轮生效，之后幂等。

    会话携带 learning_context（平台正式链路）时，课程计划由 course_adapter
    从已发布知识包/课堂动态生成；否则读本地课时（lesson-data/... 或老师上传的课时）。
    """
    if state.get("host_phase") != "uninitialized":
        return {}

    from apps.integration import course_adapter as _course_adapter

    plan = _course_adapter.load_plan_for_session(state)
    if plan is None:
        lesson_id = state.get("lesson_id") or ""
        lesson = load_lesson(lesson_id)
        if lesson is None:
            # student_status 必须一起置 ended —— 会话层靠 host_phase=="ending" 且
            # student_status=="ended" 才把 lesson_status 落成 ended；少了它，这一节
            # 会卡在 running，心跳线程永远在跑。
            return {
                "host_phase": "ending",
                "student_status": "ended",
                "reply_text": "开课失败：这门课的课时没有加载成功，请返回重新选择，或联系老师检查课程发布状态。",
                "advance_reason": "课时不存在",
            }
        plan, _segments = lesson
        problems = validate_plan(plan, uploaded=is_uploaded_lesson(lesson_id))
    else:
        # 平台发布的计划：段落/阶段来自已发布内容，不校验本地文件是否存在
        problems = validate_plan(plan)

    # 启动校验（任一失败 → 拒绝开课）
    if problems:
        return {
            "host_phase": "ending",
            "student_status": "ended",
            "reply_text": "开课校验失败：\n- " + "\n- ".join(problems),
            "advance_reason": "开课校验失败",
        }

    enabled = [s for s in plan["stages"] if s.get("enabled")]
    policy = plan["advance_policy"]

    # 星级基线：平台会话从 student schema 读该学生的掌握度（跨课次延续）。
    # 非平台会话没有 userId，无从落库，基线为空（每节课从 0 星起）。
    kp_stars: dict[str, int] = {}
    try:
        ctx = state.get("platform") or {}
        if ctx.get("userId"):
            from apps.integration import config as _cfg
            from apps.integration import persistence as _persist
            if not _cfg.demo_mode():
                kp_stars = _persist.read_mastery(
                    user_id=str(ctx["userId"]),
                    course_id=ctx.get("courseId") or "",
                    publication_id=ctx.get("publicationId") or "",
                )
    except Exception:
        kp_stars = {}

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
    from apps.integration import prompt_context

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
            # 平台发布的计划不依赖仓库内 stages/ 内容 —— 阶段提示词与题库
            # 由已发布内容提供（见 prompt_context）。只有本地课时才必须落盘。
            if not prompt_context.is_platform_plan(plan) and not (ROOT / "stages" / stage_id).is_dir():
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
        platform_plan = prompt_context.is_platform_plan(plan)
        for seg in segments:
            seg_id = seg.get("id")
            if not seg_id:
                problems.append("有段落缺 id")
            # 平台发布的计划把段落内联在 plan 里（与上传课时同理），
            # 本地 lesson-data/segments/ 下没有对应文件 —— 不能因此拒绝开课。
            elif not platform_plan and not (SEGMENTS_DIR / f"{seg_id}.json").is_file():
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

    from apps.integration import prompt_context

    # 知识层。平台链路优先：会话带已发布内容时，事实来源是那份内容本身
    # （tutor_context 只含已发布事实，且不外泄），不再叠加本地规则文件。
    platform_context = prompt_context.tutor_context(state)
    if platform_context:
        parts.append("[已发布课程上下文]\n" + platform_context)
    else:
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
    # 课堂层：当前 segment + 绑定的 KP 全文。
    # 平台计划优先取 plan 里的段落（已发布内容），本地课时才回落到磁盘段落文件。
    if state.get("active_segment_id"):
        platform_segment = prompt_context.segment_by_id(
            plan, state["active_segment_id"]
        )
        if platform_segment:
            parts.append(
                "[当前段落]\n" + json.dumps(platform_segment, ensure_ascii=False)
            )
        else:
            seg_text = _current_segment_text(state)
            if seg_text:
                parts.append("[当前段落]\n" + seg_text)
    # 阶段层（只有复述/探究/讨论三幕有；空壳 → 占位提示）
    # 复述阶段只读 prompt.md（questions.md / rubric.md 已删）；
    # 探究 / 讨论阶段仍读 questions.md + prompt.md + rubric.md。
    # 平台链路下这三阶段的内容由已发布内容提供，不读仓库内阶段文件。
    if phase in ("recap_discussion", "deep_inquiry", "class_discussion") and not platform_context:
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
            phase,
            state.get("unresolved") or [],
            state.get("lesson_id"),
            state.get("lesson_plan"),
        )
        updates["question_queue"] = queue
        updates["q_index"] = 0
        updates["unresolved"] = [q["kp_id"] for q in queue]
    elif phase == "guided_learning" and not state.get("unresolved"):
        # 讲解阶段的"未关闭目标" = 全部段落涉及的 KP（讲过 ≠ 关闭）
        kps: list[str] = []
        if prompt_context.is_platform_plan(plan):
            # 平台计划的段落在 plan 里，没有本地段落文件可读
            segments = plan.get("segments", [])
        else:
            lesson = load_lesson(state.get("lesson_id") or "")
            segments = lesson[1] if lesson else []
        for seg in segments:
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
        title = plan.get("lesson_title") or plan.get("title") or "今天的课程"
        lead = (
            "这节课先看一段讲解视频，看完之后我们一起复述一遍，"
            "再结合实际想一想，这个知识能解决什么实际问题。"
            if stage_delivery(state) == "video" else
            "讲完之后我们一起复述一遍，再结合实际想一想，这个知识能解决什么实际问题。"
        )
        reply = f"上课！今天我们讲「{title}」。{lead}"
        return {"reply_text": reply, "student_status": "active"}
    if phase == "ending":
        return {"reply_text": "这节课就到这里，下课！"}
    return {"reply_text": "（老师插话）好，我们继续。"}


def _segments(plan: dict) -> list[dict]:
    return plan.get("segments") or []


def _segment_detail(plan: dict, seg_id: str | None) -> dict | None:
    """按 id 取段落详情。平台计划的段落内联在 plan 里，
    旧式课时散在 lesson-data/segments/，新式内联在课时文件里。"""
    if not seg_id:
        return None
    from apps.integration import prompt_context

    # 平台计划：段落是已发布内容的一部分，不在本地任何文件里
    platform_segment = prompt_context.segment_by_id(plan, seg_id)
    if platform_segment:
        return platform_segment
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
    from apps.integration import prompt_context

    # 平台链路的事实边界：背景里的 [已发布课程上下文] 是唯一可用事实来源。
    # 独立演示模式沿用本地课程文件，不加这条约束。
    fact_rule = (
        "【课堂背景】中的已发布课程事实是唯一可用的事实来源，"
        "不得使用其他课程的内容，也不得自行补充事实。"
        if prompt_context.is_platform_plan(state.get("lesson_plan") or {})
        else ""
    )
    system = (
        "你是当前这节课的 AI 教师。课程、教材和章节由【课堂背景】与【本轮指令】提供的内容决定。"
        "你只负责当前单节课的问答与引导，不规划整个学期，也不向学生谈论跨课次的进度。\n\n"
        "【角色与目标】学生问什么，就先把什么回答清楚；同时指出学生答案中的误区，并补上正确的理解。"
        "不要用连续提问代替讲解。学生不懂时，先给他一小段知识讲解作为台阶，再提出下一步问题——"
        "既不直接一次性倾倒完整答案，也不机械地反复追问。\n\n"
        "【本轮指令】以【本轮指令】为教学目标和流程边界，不要逐字复述指令或把它说成生硬的话术。"
        "在不改变本轮教学动作、不擅自改变课堂流程的前提下，自然回应学生刚才的表达，并用承接语让对话连贯。"
        + fact_rule
        + "\n\n【每轮回答顺序】按需组织，可删去暂时不需要的步骤，但不能只提问、不回答：\n"
        "1. 直接回应学生的问题或回答；\n"
        "2. 用当前课程的术语给出准确定义或结论；\n"
        "3. 解释原因、过程或推导；\n"
        "4. 给出一个最小例子；\n"
        "5. 必要时给出一个反例；\n"
        "6. 指出学生答案中正确、错误和缺失的部分；\n"
        "7. 最多再问一个确认或推进问题。\n\n"
        "【提问限制】每轮最多问一个问题；学生明显答不上来时，不要接着问同类问题，"
        "先给知识讲解作为台阶，再问一个更小的问题。禁止用“你再想想”“你觉得呢”这类空话拖延讲解。"
        "不要为了追问而追问——讲新知识时讲解与提问比例约为 9:1，复习或查缺补漏时约为 7:3。\n\n"
        "【WAIT-WHAT 重讲协议】当学生表示没听懂、没跟上，或回答明显偏离问题时："
        "1. 停止原来的提问；2. 用一句话说明上一段原本要讲什么；"
        "3. 退回到一个更简单的前置概念，用短句、主动语态重新讲解，一句只表达一个意思；"
        "4. 使用当前课程统一的术语和符号；5. 给一个具体例子，必要时再给一个反例；"
        "6. 讲清后再给一个最小的问题请学生尝试；7. 学生仍不确定时，给更细的台阶继续教，"
        "而不是一次性公布全部答案。WAIT-WHAT 是先降低难度再重新讲一遍，不是换一种方式继续追问。\n\n"
        "【纠错格式】学生回答后，按顺序纠正：1. 你答对的部分是什么；2. 你答错或不准确的部分是什么；"
        "3. 更准确的表述是什么；4. 你为什么会形成这个误区；5. 下次遇到这类问题应先看什么。"
        "评价回答内容，不评价学生人格；温和、具体、诚实，不把未覆盖的内容说成错误。\n\n"
        "【通用讲解方式】按问题类型自然调整：概念（定义、边界、例子、反例、相近概念的区别）、"
        "数学（目标、条件、推导、结论、常见错误）、代码（目标、输入输出、数据流、示例、错误原因）、"
        "文科（观点、证据、解释逻辑、其他解释、结论限制）、实验（目的、变量、步骤、现象、结论、误差来源）。"
        "不要把一门课的术语带到另一门课；同一词在不同课程含义不同时，以当前课程教材为准。\n\n"
        "【资料来源】优先使用【课堂背景】中的课件、教材与教师说明；资料没有提供时可给通用解释，"
        "但要说明“这是通用解释，最终以本节课资料为准”；无法确定答案时明确说明缺少什么条件，不得编造课程内容。\n\n"
        "【系统与输出边界】绝对不要向学生提及任何系统内部情况：保存/写盘/落盘、失败/报错/错误/error/异常、"
        "日志/记录、评分/星级/掌握档案、模型/接口/网络等技术细节；即使这类问题确实发生，也只当作没发生，继续正常上课。"
        "【课堂背景】仅用于理解课程和学生情况，不要照读或提及背景材料。"
        "输出要求：中文口语，通常 1–3 句；需要解释时按上面的顺序适当展开；表达具体、友好、自然；"
        "不写标题、不用 Markdown、不加括号注释。"
    )
    return llm_chat(
        system,
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
        return NO_LLM_NOTICE, False
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
    if msg.strip():
        # 累积整课对话，供下课前的 LLM 掌握度评定使用（见 _assess_mastery_with_llm）
        updates["dialogue_log"] = [{"role": "student", "text": msg}]
    plain = ""
    directive = ""
    decision_turn = None   # 复述/探究「学生作答」轮：由 LLM 判定推进/留守（见下方第二层）
    # 心跳轮默认静默；只有下面明确置 True 的分支（讲到新段落 / 抛出新一问）才开口。
    # 否则每隔几秒就重复一句"很好，我们接着往下讲"，课堂上没法听。
    tick = bool(state.get("tick_only"))
    speak = not tick

    # 老师按「下一环节」：本轮 teach 不说话，由 advance_stage 的开场白接管。
    # 否则会拼出"刚抛出一个问题、下一秒又宣布换环节"的缝合怪回复。
    if state.get("external_event") in (EVENT_NEXT_STAGE, EVENT_END_LESSON):
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
        # ── 视频讲解模式：视频负责主讲，AI 回答学生主动提出的问题 ──
        # 视频播完才推进段落游标；提问不改变播放进度和阶段。
        if stage_delivery(state) == "video":
            if state.get("external_event") == EVENT_MEDIA_DONE:
                segs = _segments(plan)
                updates["segment_cursor"] = len(segs)
                played = [
                    {"segment_id": s.get("id"), "at": state.get("now")}
                    for s in segs
                ]
                updates["played_media"] = list(state.get("played_media") or []) + played
            if msg.strip() and state.get("speaker") == "student" and not tick:
                directive = (
                    "学生正在观看本课视频前的引导阶段，刚主动提出问题。"
                    "直接回答这个问题；只依据课堂背景中的本课已发布内容，"
                    "信息不足时坦诚说明并引导学生在视频中留意相关内容。"
                    "不要代替视频完整讲课，不要要求切换阶段或宣称视频已经播放完。"
                )
                polished = llm_polish(state, directive) if llm_available() else None
                updates["reply_text"] = polished.strip() if polished else NO_LLM_NOTICE
                updates["llm_used"] = bool(polished)
            else:
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
                    else f"本课（{plan.get('lesson_title') or plan.get('title') or '本节课'}）已讲过的内容"
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
        if pending and msg.strip():
            # 学生回答了上一轮挂起的问题 → 反馈 + 判定推进/留守
            kp = pending["kp_id"]
            updates["current_target"] = kp
            attempt = state.get("attempts", 0) + 1

            # 深层探究：超过 5 轮仍在讨论的问题做记录（确定性记账，与判定无关）
            notes = [dict(item) for item in (state.get("unresolved_question_notes") or [])]
            tracked_note = next((
                item for item in reversed(notes)
                if item.get("phase") == phase
                and item.get("kp_id") == kp
                and item.get("question") == pending["question"]
                and item.get("status") == "继续引导中"
            ), None)
            if phase == "deep_inquiry" and attempt > MAX_DEEP_INQUIRY_ATTEMPTS and tracked_note is None:
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
            if tracked_note is not None:
                updates["unresolved_question_notes"] = notes

            if wrap:
                # 预算耗尽收尾：不再抛下一问，留给下一幕/下节课
                updates["pending_question"] = None
                updates["attempts"] = 0
                lines.append("时间到了，这个问题我们先收在这里。")
                dl.append("本阶段时间到了，简短收尾。**绝对不要再提新问题**。")
            else:
                # ── 答没答上交给 LLM 判定，不再写死关键词表 ──────────
                # 骨架只备「兜底文案（默认推进）」与「判定指令」；推进/留守的
                # 落盘等 LLM 返回后再做（见 _apply_question_decision）。
                nxt = queue[idx + 1] if idx + 1 < len(queue) else None
                decision_turn = {
                    "phase": phase, "kp": kp, "attempt": attempt,
                    "pending": pending, "idx": idx, "nxt": nxt,
                    "tracked_note": tracked_note, "notes": notes,
                    "msg": msg, "now": state.get("now"),
                }
                lines.append("嗯，我们来看看你的说法。")
                if nxt:
                    lines.append(f"这个我们先放一放，继续：{nxt['question']}")
                else:
                    lines.append("这一阶段的问题就到这里。")
                hint = _hint(kp, state)
                if phase == "recap_discussion":
                    dl.append(
                        f"当前是复述阶段的第 {attempt} 次回应。当前问题：{pending['question']}\n"
                        f"可参考的引导线索：{hint}\n"
                        "判断学生是否用自己的话回应了当前问题（哪怕不完整、有错也算“答了”；"
                        "只有明确表示答不上来才算“没答”）。\n"
                        + (f"若“答了”，按纠错格式反馈后自然过渡到下一题：{nxt['question']}。\n"
                           if nxt else "若“答了”，按纠错格式反馈后收束本阶段。\n")
                        + "若“没答”，留在当前题，先给一小段知识讲解作台阶，再请学生尝试；"
                          "逐级增加帮助，但不要公布完整答案、不要提出下一题。"
                    )
                else:
                    dl.append(
                        f"当前是深层探究的第 {attempt} 次回应。当前问题：{pending['question']}\n"
                        f"可参考的引导线索：{hint}\n"
                        "判断学生是否已经说清了关键原因或推导过程。\n"
                        + (f"若说清了，简短肯定其推理后过渡到下一题：{nxt['question']}。\n"
                           if nxt else "若说清了，简短肯定其推理后收束本阶段。\n")
                        + "若还没说清，留在当前题，围绕原因、依据或例子追问一个小问题；"
                          "逐级缩小问题，但不要公布完整答案、不要提出下一题、也不要切换环节。"
                    )
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

    # ── 复述/探究「学生作答」：先让 LLM 判定「答没答」，再按判定推进或留守 ──
    if decision_turn is not None:
        if llm_available():
            reply, advance = _polish_question_turn(state, directive)
            if reply is not None:
                updates["reply_text"] = reply
                updates["llm_used"] = True
                _apply_question_decision(updates, decision_turn, advance)
                return updates
            # 判定/解析失败：走确定性兜底（默认推进）
            updates["reply_text"] = plain
            updates["llm_used"] = False
            _apply_question_decision(updates, decision_turn, True)
            return updates
        updates["reply_text"] = NO_LLM_NOTICE
        updates["llm_used"] = False
        _apply_question_decision(updates, decision_turn, True)
        return updates

    # ── 第二层：LLM 只负责把指令变成自然语言（可失败）──
    if llm_available():
        polished = llm_polish(state, directive)
        if polished:
            updates["reply_text"] = polished.strip()
            updates["llm_used"] = True
            return updates

    updates["reply_text"] = NO_LLM_NOTICE if not llm_available() else plain
    updates["llm_used"] = False
    return updates


def _apply_question_decision(updates: dict, d: dict, advance: bool) -> None:
    """把 LLM 的「推进 / 留守」判定落到状态机上。

    - 推进：清空 attempts，题目游标前进到下一题；探究阶段若此前有「超过 5 轮」
      的记录，标记为已由学生推导。
    - 留守：attempts 累加，题目与游标保持不变，下一轮继续同一道题。
    """
    if advance:
        updates["attempts"] = 0
        if d["phase"] == "deep_inquiry" and d["tracked_note"] is not None:
            note = d["tracked_note"]
            note["status"] = "已由学生推导"
            note["student_solution"] = d["msg"]
            note["resolved_at"] = d["now"]
            note["note"] = "超过 5 轮后继续引导，学生已自行推导"
            updates["unresolved_question_notes"] = d["notes"]
        updates["q_index"] = d["idx"] + 1
        updates["pending_question"] = d["nxt"]
    else:
        updates["attempts"] = d["attempt"]
        updates["pending_question"] = d["pending"]
        updates["q_index"] = d["idx"]
    updates["current_question"] = (updates.get("pending_question") or d["pending"]).get("question")


def _polish_question_turn(state: ClassroomState, directive: str) -> tuple[str | None, bool | None]:
    """复述/探究阶段：让 LLM 判定「答没答上」并给出回应。

    返回 (reply, advance)。reply=None 表示未接上或解析失败，由调用方走确定性兜底；
    advance 只在 reply 有效时才有意义：True=推进下一题，False=留守本题继续引导。

    取代原先写死的 _is_nonanswer / _deep_answer_has_depth 关键词表：把自然语言
    当关键词匹配既脆又漏（“我忘了”漏判导致上下文对不上），这里改成 LLM 依据
    对话自己判断，只回一个结构化信号，编排层照它走。
    """
    phase = state.get("host_phase")
    elapsed = state.get("stage_elapsed_minutes", 0.0)
    budget = state.get("stage_budget_minutes", 0.0)
    background = (state.get("assembled_prompt") or "").strip()
    system = (
        "你是当前这节课的 AI 教师。学生回答了上一轮你提出的问题，"
        "请判断他有没有给出实质性回答，并给出回应。\n"
        "判断标准：只要学生用自己的话回应了问题（哪怕不完整、有错误），就算“答了”；"
        "只有像“不知道”“忘了”“不会”这类明确表示答不上来，才算“没答”。\n"
        "回应要求：先点出学生说对的部分，再补缺失或纠正不准确处，给出更准确的表述；"
        "“没答”时先给一小段知识讲解作台阶，再请学生尝试，不要一次性公布完整答案。\n"
        "只输出 JSON：{\"reply\": \"你要对学生说的话\", \"advance\": true 或 false}\n"
        "advance=true 表示已实质性作答、可推进到下一题；false 表示没答上、留在本题继续引导。"
    )
    user = (
        (f"【课堂背景】\n{background}\n\n" if background else "")
        + f"当前阶段：{STAGE_NAMES.get(phase, phase)}（已进行 {elapsed:.0f}/{budget:.0f} 分钟）\n"
        f"【本轮指令】\n{directive}\n\n"
        f"学生刚才说：{state.get('student_message', '') or '（未发言）'}\n\n"
        "直接输出 JSON。"
    )
    raw = llm_chat(system, user)
    if not raw:
        return None, None
    try:
        body = raw.strip()
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            return None, None
        parsed = json.loads(body[start:end + 1])
        reply = parsed.get("reply")
        advance = parsed.get("advance")
        if not isinstance(reply, str) or not reply.strip():
            return None, None
        if not isinstance(advance, bool):
            return None, None
        return reply.strip(), advance
    except (ValueError, TypeError):
        return None, None


def _hint(kp_id: str, state: ClassroomState | None = None) -> str:
    from apps.integration import prompt_context

    # 平台链路：提示语由已发布知识点提供（含 misconceptions），优先于通用提示
    if state:
        platform_hint = prompt_context.hint(state.get("lesson_plan") or {}, kp_id)
        if platform_hint:
            return platform_hint
    return "结合刚才讲过的内容，从它的定义和作用出发想一想，并举一个例子。"


def judge_mastery(state: ClassroomState) -> dict:
    """记录本轮的掌握证据。

    - guided_learning：讲过即记 1 星（已接触）
    - recap_discussion / deep_inquiry：不再用写死关键词判星级。星级由
      下课前的 LLM 依据知识点与学生对话综合评定（见 _assess_mastery_with_llm）；
      这里只记录学生原话，供 stage_snapshots / 学情导出 / LLM 判定使用。
    - 星级只升不降。
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
        if kp and msg.strip():
            # 不判星级，只留证据：学生原话 + 本轮阶段。
            evidence.append(f"{kp}: 学生原话「{msg[:60]}」")
            kp_meta[kp] = {
                "last_source": "dialogue", "last_stage": phase,
                "last_evidence": msg, "updated_at": now,
            }

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
    if ev == EVENT_END_LESSON:
        return {"target_phase": "ending", "advance_reason": "老师按了「结束本节课」"}
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

    # 关键词证据匹配已删（星级改由下课前的 LLM 综合评定），
    # 切幕不再按「证据充分」触发，统一按时间预算推进。
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
    if state.get("external_event") == EVENT_END_LESSON:
        rest = []   # 主动下课：跳过剩余阶段，直接进 ending
    if not rest:
        # 总结要算上本幕（deep_inquiry）刚拍的这条快照。
        # 下课前的掌握度评定：交给 LLM 依据整课对话综合判定（取代写死关键词），
        # 再用评定后的星级写总结，并把更新带进 out 供会话层落盘。
        kp_stars, mastery_updates = _assess_mastery_with_llm(state)
        remark, gen = _ending_remark({**state, "kp_stars": kp_stars}, snapshot)
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
            "kp_stars": kp_stars,
            "mastery_updates": mastery_updates,
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
        queue = build_question_queue(
            nxt, carried, state.get("lesson_id"), state.get("lesson_plan")
        )
        if queue:
            out["question_queue"] = queue
            out["llm_used"] = gen or any(q.get("source") == "platform-published AI-generated" for q in queue)
            out["q_index"] = 0
            out["pending_question"] = queue[0]
            out["current_question"] = queue[0]["question"]
            out["unresolved"] = [q["kp_id"] for q in queue]
            if llm_available():
                out["reply_text"] = (
                    out["reply_text"] + f"\n\n先来第一问：{queue[0]['question']}"
                )
    if snapshot:
        out["stage_snapshots"] = [snapshot]
    return out


def _assess_mastery_with_llm(state: ClassroomState) -> tuple[dict[str, int], list[dict]]:
    """下课前的掌握度评定：让 LLM 依据整课对话与知识点综合判定星级。

    取代原先写死的 EVIDENCE_GROUPS 关键词匹配。返回 (新的 kp_stars, mastery_updates)。
    - 只升不降；LLM 未接入、无对话、或调用失败时原样返回，不影响下课。
    - 输出格式为 {kp_id: 1~4 的整数星级}，解析失败直接忽略。
    """
    kp_stars = dict(state.get("kp_stars") or {})
    dialogue = state.get("dialogue_log") or []
    if not dialogue or not llm_available():
        return kp_stars, []

    # 本课涉及的知识点：已记星级的 + 未关闭目标 + 计划/段落里声明的，去重保序。
    # 这样视频讲解模式（不逐段 bump 1 星）里的知识点也不会漏评。
    kp_ids = list(dict.fromkeys(
        list(kp_stars.keys()) + list(state.get("unresolved") or [])
    ))
    plan = state.get("lesson_plan") or {}
    for kp in plan.get("knowledge_points") or []:
        kid = kp.get("id") or kp.get("kp_id")
        if kid:
            kp_ids.append(str(kid))
    from apps.integration import prompt_context
    if prompt_context.is_platform_plan(plan):
        segments = plan.get("segments", [])
    else:
        lesson = load_lesson(state.get("lesson_id") or "")
        segments = lesson[1] if lesson else []
    for seg in segments:
        for kid in seg.get("knowledge_point_ids") or []:
            kp_ids.append(str(kid))
    kp_ids = list(dict.fromkeys(kp_ids))
    if not kp_ids:
        return kp_stars, []

    lesson_id = state.get("lesson_id")
    kp_lines = "\n".join(f"- {kp}：{kp_title(kp, lesson_id)}" for kp in kp_ids)
    dialogue_lines = "\n".join(
        f"{'学生' if d.get('role') == 'student' else 'AI'}：{d.get('text')}"
        for d in dialogue
    )
    system = (
        "你是教学评估助手。根据学生在课堂对话中的实际表现，为每个知识点评定掌握星级。"
        "星级含义：1=已接触、2=初步理解、3=理解中、4=接近掌握。"
        "只依据对话中的证据评定；对话里没有体现的知识点保持原星级或评为 1 星，不要凭空拔高。"
        "只返回 JSON 对象：键为知识点编号，值为 1~4 的整数。"
    )
    raw = llm_chat(
        system,
        f"本课知识点：\n{kp_lines}\n\n课堂对话：\n{dialogue_lines}\n\n"
        "请为每个知识点给出星级，只输出 JSON。",
    )
    if not raw:
        return kp_stars, []

    # 容错：只取第一个 { 到最后一个 } 之间的 JSON，忽略前后多余文字。
    try:
        body = raw.strip()
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            return kp_stars, []
        parsed = json.loads(body[start:end + 1])
        if not isinstance(parsed, dict):
            return kp_stars, []
    except (ValueError, TypeError):
        return kp_stars, []

    updates: list[dict] = []
    now = state.get("now")
    for kp_id in kp_ids:
        val = parsed.get(kp_id)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        new_stars = max(1, min(4, int(val)))
        old = kp_stars.get(kp_id, 0)
        if new_stars > old:
            kp_stars[kp_id] = new_stars
            updates.append({
                "kp_id": kp_id, "old_stars": old, "new_stars": new_stars,
                "old_status": STAR_STATUS.get(old, "未检测"),
                "new_status": STAR_STATUS[new_stars],
                "source": "llm-assessed", "stage": "ending",
                "evidence": "LLM 依据课堂对话综合评定",
                "occurred_at": now,
            })
    return kp_stars, updates


def _ending_remark(state: ClassroomState, pending_snapshot: dict | None) -> tuple[str, bool]:
    """下课那句话。能用模型就说人话，不能用就退回模板。

    为什么不等下一轮 teach 再说：切进 ending 就要立刻把 student_status 置为 ended，
    会话层据此停心跳——晚了这句话就永远没人替老师说了。
    """
    plain = _ending_summary(state, pending_snapshot=pending_snapshot)
    if not llm_available():
        return NO_LLM_NOTICE, False
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
    """持久化已迁到会话层：学习数据（消息/掌握度/事件/报告）由
    apps.integration.persistence 写 student schema，不再写本地文件。

    这个节点保留为占位——图拓扑（judge_advance/advance_stage → write_state →
    format_reply）依赖它，现在它什么都不做。
    """
    return {}


def format_reply(state: ClassroomState) -> dict:
    """组装最终回复与播报标记，并把 AI 本轮的话追加进整课对话记录。"""
    reply = state.get("reply_text", "")
    out = {"reply_text": reply, "speech_kind": "auto" if reply else "none"}
    if reply:
        out["dialogue_log"] = [{"role": "ai", "text": reply}]
    return out


# ═══════════════════════════════════════════════════════════════
# 路由：判断写进 state，路由函数只读不判
# ═══════════════════════════════════════════════════════════════

def route_after_classify(state: ClassroomState) -> str:
    """心跳与外部事件都走教学层：游标推进、静默判定、切幕依据全在 teach/judge 里。
    走 host_event 的话 media_done 的游标推进根本不会执行（那边只管开场白和插话），
    表现为"视频播完报了却没切幕"——踩过一次，别再犯。

    是否真的开口由 teach 判断——没新内容就静默（reply_text 为空）。
    """
    if state.get("external_event") in (EVENT_MEDIA_DONE, EVENT_NEXT_STAGE, EVENT_END_LESSON):
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
        "dialogue_log": [],
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
