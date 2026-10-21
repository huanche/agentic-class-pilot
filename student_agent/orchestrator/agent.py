"""主动引导智能体 —— 真实 LangGraph 编排器实现。

依据 `orchestrator/ORCHESTRATOR.md` 规范实现，覆盖全部 11 个节点：
load_plan / tick / load_context / classify_turn / host_event / teach /
judge_mastery / judge_advance / advance_stage / write_state / format_reply

关键约定（与规范一致）：
- `now` 由会话层注入 state，图内任何节点不调 datetime.now() → 可单测、可回放。
- 判断写进 state（target_phase），路由函数只读不判。
- `stage_snapshots` 用 Annotated[list, operator.add] 累加，不覆盖。
- 教学事实、问题与提示来自平台发布的学习上下文，不从仓库内的课程文件回退读取。

LLM 接入（可选）：
    设置环境变量 AGENT_LLM_BASE_URL / AGENT_LLM_API_KEY / AGENT_LLM_MODEL
    （任意 OpenAI 兼容 /chat/completions 端点）后，teach 节点改用真实大模型。
    未配置时 teach 走规范第 8 节的确定性降级行为，整张图照样能跑完整节课。
    星级评定由下课前的 LLM 依据整课对话综合判定（见 _assess_mastery_with_llm）；
    复述/探究阶段「答没答上」的推进/留守也交给 LLM 判定，不再写死关键词表。

课堂通过平台入口启动，由 apps/server.py 托管会话。
"""

from __future__ import annotations

import json
import operator
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta
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
    "tutoring": "课后辅导",
}
STAR_STATUS = {1: "已接触", 2: "初步理解", 3: "理解中", 4: "接近掌握"}

# 全局开关：视频最终播完 → 进入「课后辅导」（默认开启）。
# 关闭时回到原有编排（复述 → 探究 → 讨论）；三个旧阶段的代码保留不删。
TUTORING_ENV_VAR = "AGENT_POST_VIDEO_TUTORING"


def post_video_tutoring_enabled() -> bool:
    return os.environ.get(TUTORING_ENV_VAR, "1").strip().lower() \
        not in ("0", "false", "no", "off")

# 外部事件取值（会话层注入 `external_event`）
EVENT_BEGIN = "begin"            # 课堂开始
EVENT_MEDIA_DONE = "media_done"  # 一段视频/素材播放完成
EVENT_NEXT_STAGE = "next_stage"  # 老师按"下一环节"，强制切幕
EVENT_END_LESSON = "end_lesson"  # 老师按"结束本节课"，直接下课（跳过剩余阶段）


def stage_delivery(state: ClassroomState) -> str:
    """讲解阶段（guided_learning）的授课方式，来自平台发布的课堂计划：

    - ``video``：视频由平台课堂播放器承载，完成事件由播放器回报。
    - ``narration``：AI 逐段讲解。
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

    标题从平台课程上下文注册表读取。

    模型生成的回复要用标题，**不能把 KP-004 这类内部编号说给学生听**。
    取不到时原样返回编号（宁可说编号，也不要编标题）。
    """
    # 平台课程的知识点标题由集成层建计划时注册（course_adapter），
    # 查得到就绝不说 KP-xxx 这类内部编号。
    registered = _PLAN_KP_TITLES.get(kp_id)
    if registered:
        return registered

    return kp_id


MAX_DEEP_INQUIRY_ATTEMPTS = 5


def build_question_queue(
    phase: str,
    unresolved: list[str],
    lesson_id: str | None = None,
    plan: dict | None = None,
) -> list[dict]:
    """根据平台发布课程内容为复述/探究阶段组装问题队列。

    题目由已发布知识点包提供（prompt_context）。

    没有平台计划或知识点时返回空队列，不使用仓库内的旧课程题库兜底。
    """
    from apps.integration import prompt_context
    return prompt_context.question_queue(phase, plan or {}, unresolved, generate=llm_chat)


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
        "recap_discussion", "deep_inquiry", "class_discussion", "tutoring", "ending",
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

    # ── 课后辅导（工单 02：意愿与时间预算）──
    # ⚠️ 同上：LangGraph 只保留本 TypedDict 声明过的键，新键必须在此声明。
    tutoring_order: list[str]               # 复习顺序（kp_id 列表，学生指定在前，其余按目录补齐）
    tutoring_self_ratings: dict[str, int]   # 学生自评 1–5 星（只表达意愿，与系统星级分开存储）
    tutoring_planned_minutes: int           # 当前计划时长（分钟）：学生报的时长，或进辅导时的默认值
    tutoring_planned_end_at: str | None     # 计划结束时间戳：学生报时长那一刻起算；未报时从进辅导起按默认时长起算
    tutoring_cursor: int                    # 复习游标：tutoring_order 里当前推进到第几个（判对 +1）
    tutoring_active_kp: str | None          # 正在讲的知识点（显式记录；高亮/载荷以它为准，不从顺序+游标推导）
    tutoring_stars: dict[str, int]          # 辅导作答证据星（掌握条/辅导反馈用；课堂「已接触」基线不混入）
    tutoring_question: dict | None          # 当前检测题 {kp_id, question, asked_at, hint_given, was_fresh, wrong_count}
    tutoring_last_judgement: dict | None    # 本轮作答判定（会话层据此落学习事件；无判定为 None）
    tutoring_asked: list[str]               # 已见题干清单（出题去重：新题必须避开）
    tutoring_stats: dict                    # 答题统计 {correct, wrong, hinted_correct}（反馈报告用）
    tutoring_end_confirm_pending: bool      # LLM 识别到结束意图，等学生确认（防误杀）
    tutoring_end_confirmed: bool            # 学生已确认结束（judge_advance 据此切 ending，随切幕清零）

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

    课程计划由 course_adapter 从平台已发布知识包/课堂动态生成；缺少平台上下文时拒绝开课。
    """
    if state.get("host_phase") != "uninitialized":
        return {}

    from apps.integration import course_adapter
    plan = course_adapter.load_plan_for_session(state)
    if plan is None:
        return {
            "host_phase": "ending", "student_status": "ended",
            "reply_text": "开课失败：未取得平台发布的课程内容，请从课程平台重新进入。",
            "advance_reason": "平台课程上下文缺失",
        }
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

    # 全局开关开启：视频讲解之后的复述/探究/讨论三个阶段下线，
    # 换成一个「课后辅导」阶段接住视频播完的时刻。开关关闭时序列原样，
    # 旧编排（复述→探究→讨论）一分不改地回来。
    stage_sequence = [s["id"] for s in enabled]
    if post_video_tutoring_enabled():
        kept = [sid for sid in stage_sequence
                if sid not in ("recap_discussion", "deep_inquiry", "class_discussion")]
        stage_sequence = kept + ["tutoring"]

    # 星级基线：平台会话从 student schema 读该学生的掌握度（跨课次延续）。
    # 非平台会话没有 userId，无从落库，基线为空（每节课从 0 星起）。
    kp_stars: dict[str, int] = {}
    try:
        ctx = state.get("platform") or {}
        if ctx.get("userId"):
            from apps.integration import persistence as _persist
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
        "remaining_stages": stage_sequence,
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


def validate_plan(plan: dict) -> list[str]:
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
    if prompt_context.is_platform_plan(plan):
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
            kp_id = kp.get("id") or kp.get("kp_id")
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
        problems.append("课程计划必须来自平台发布内容")
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
    """装配平台已发布内容与当前阶段状态；复述/探究问题由平台内容生成。"""
    phase = state.get("host_phase")
    parts: list[str] = []

    from apps.integration import prompt_context

    # 知识层只读取平台已发布内容，不叠加仓库内的旧课程规则文件。
    platform_context = prompt_context.tutor_context(state)
    if not platform_context:
        raise ValueError("缺少平台已发布课程上下文")
    parts.append("[已发布课程上下文]\n" + platform_context)
    # 计划层（仅当前阶段配置）
    plan = state.get("lesson_plan") or {}
    for s in plan.get("stages", []):
        if s["id"] == phase:
            parts.append(f"[阶段计划] {s}")
    # 课堂层：从平台计划取当前段落及绑定的知识点。
    if state.get("active_segment_id"):
        platform_segment = prompt_context.segment_by_id(
            plan, state["active_segment_id"]
        )
        if platform_segment:
            parts.append(
                "[当前段落]\n" + json.dumps(platform_segment, ensure_ascii=False)
            )
    # 阶段提示由已发布内容提供，不读仓库内的阶段模板文件。
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
        segments = plan.get("segments", [])
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
    """按 id 从平台发布计划中取段落详情。"""
    if not seg_id:
        return None
    from apps.integration import prompt_context

    return prompt_context.segment_by_id(plan, seg_id)


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


def _lesson_kp_catalog(state: ClassroomState) -> list[tuple[str, str]]:
    """本节课的知识点目录（保序去重）：[(kp_id, 标题), …]。

    平台化后知识点只来自平台下发的教学计划（声明在前、段落补充在后）；
    标题统一走 kp_title（平台注册表 > KNOWLEDGE-BASE.md）。
    """
    plan = state.get("lesson_plan") or {}
    ids: list[str] = []
    for kp in plan.get("knowledge_points") or []:
        kid = str(kp.get("kp_id") or kp.get("id") or "").strip()
        if kid:
            ids.append(kid)
    for seg in plan.get("segments") or []:
        for kid in seg.get("knowledge_point_ids") or []:
            kid = str(kid).strip()
            if kid:
                ids.append(kid)
    lesson_id = state.get("lesson_id")
    return [(kid, kp_title(kid, lesson_id)) for kid in dict.fromkeys(ids)]


_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(token: str) -> int:
    return int(token) if token.isdigit() else _CN_NUM.get(token, 0)


def _parse_tutoring_order(msg: str, catalog: list[tuple[str, str]]) -> list[str] | None:
    """学生指定的复习顺序：按开场固定编号**或知识点名字**点名。

    认的写法：「先 2 再 1」「先复习第 2 个」「先讲时间片轮转再复习调度」。
    名字点名要求消息里有「先/顺序」这类排序词——只在提问里出现知识点
    名字（「三级调度是什么意思？」）不算定顺序。
    没点名 → None；未提到的知识点按目录顺序补在后。
    """
    n = len(catalog)
    first = re.search(
        r"先\s*(?:复习\s*|从\s*|看\s*|讲\s*|学\s*)?(?:第\s*)?([0-9]+|[一二三四五六七八九十])",
        msg)
    picked: list[int] = []
    if first:
        picked = [_cn_num(first.group(1))]
        for m in re.finditer(
                r"(?:再|然后|接着)\s*(?:复习\s*|从\s*|看\s*|讲\s*|学\s*)?(?:第\s*)?"
                r"([0-9]+|[一二三四五六七八九十])",
                msg[first.end():]):
            picked.append(_cn_num(m.group(1)))
    deduped = list(dict.fromkeys(no for no in picked if 1 <= no <= n))
    if deduped:
        ids = [catalog[no - 1][0] for no in deduped]
        rest = [kid for kid, _title in catalog if kid not in ids]
        return ids + rest

    if re.search(r"先|顺序", msg):
        positions = []
        for kid, title in catalog:
            idx = msg.find(title) if title else -1
            if idx >= 0:
                positions.append((idx, kid))
        positions.sort()
        if positions:
            ids = [kid for _idx, kid in positions]
            rest = [kid for kid, _title in catalog if kid not in ids]
            return ids + rest
    return None


# 七分类的骨架层信号：结束 / 追问 / 求助（自评、选点、改时间由各自解析器识别）。
# 答题是兜底类：不是以上任何一类、又不是意愿表达的消息，交给工单 03 的判答链。
_TUTORING_END_PAT = re.compile(r"就到这|到此为止|今天先到|先这样|下课|结束吧|复习完[了成]|收尾吧")
_TUTORING_SKIP_PAT = re.compile(r"下一|跳过|换一[个题]|往下[一走]|继续往")
_TUTORING_QUES_PAT = re.compile(r"[?？]|为什么|怎么|什么意思|是什么|怎么办|如何|哪.*(问题|不懂)")
_TUTORING_HELP_PAT = re.compile(r"不懂|不会|没听懂|不明白|帮我|讲讲|讲一下|解释|教教我")
# LLM 提议结束后的二次确认：肯定 → 下课（judge_advance 同回合生效），否定 → 继续
_TUTORING_CONFIRM_PAT = re.compile(r"(?:是[的呀]?|对|嗯+|好[的呀]?|可以|行|要|确认|结束[吧了]?)[。！!，, ]*")
_TUTORING_DECLINE_PAT = re.compile(r"不[要会想是]|先不|还没|继续|再[聊学复习一会]|等等")


def _tutoring_question_pool(title: str) -> list[str]:
    """同知识点的确定性题池：出题去重的兜底（无模型/生成失败时轮换）。"""
    return [
        f"小检测：请用自己的话说说「{title}」讲的是什么，最好举个例子。",
        f"换个角度考考你：「{title}」和不用它会差在哪？说说你的理解。",
        f"再确认一下：如果让你给同学解释「{title}」，你会怎么讲？举一个具体例子。",
    ]


def _tutoring_generate_question(title: str, seen: list[str]) -> str | None:
    """模型出题：把已见题干喂进 prompt 避开；失败返回 None 走题池。"""
    if not llm_available():
        return None
    seen_block = "\n".join(f"- {s}" for s in seen) or "（还没有问过题）"
    raw = llm_chat(
        "你是课堂里的 AI 辅导老师，要为学生出一个知识检测题。"
        "题目必须考查给定的知识点、适合口头作答、一句话问完。"
        "不得与已问过的题目重复或高度相似。只输出题目本身，不要编号不要解释。",
        f"知识点：{title}\n已问过的题（必须避开）：\n{seen_block}\n请出下一道检测题：",
    )
    text = (raw or "").strip()
    return text or None


def _tutoring_pick_question(title: str, seen: list[str]) -> tuple[str, bool]:
    """选题：优先模型生成（避开已见），失败走确定性题池轮换。

    返回 (题干, 是否未见)。题池耗尽后复用旧题，标记不新鲜——
    答对也封顶 4 星（量规的 stale_question_max_stars）。
    """
    generated = _tutoring_generate_question(title, seen)
    if generated and generated not in seen:
        return generated, True
    for q in _tutoring_question_pool(title):
        if q not in seen:
            return q, True
    return _tutoring_question_pool(title)[0], False


def _tutoring_extract_intent_llm(msg: str, catalog: list[tuple[str, str]]) -> dict:
    """模型翻译官：把学生的话翻成结构化意图（一行 JSON）。

    只翻译不决策——返回的字典还要过 `_validated_tutoring_intent`
    的骨架校验才允许写状态。模型缺席 / 输出不是 JSON → {}，
    行为退回纯正则。
    """
    if not llm_available():
        return {}
    listing = "、".join(f"{i}.{title}" for i, (_kid, title) in enumerate(catalog, 1))
    raw = llm_chat(
        "你是课后辅导的意图解析器。把学生这句话里表达的复习意愿抽成一行 JSON，"
        "只输出 JSON 本身，不要解释。可选字段："
        "order=知识点编号数组（按学生想复习的先后排序，只列他点到的，没点到的不要编）；"
        "self_ratings=对象（键=知识点编号，值=1 到 5 的自评星）；"
        "duration_minutes=他想复习的分钟数（整数）。"
        "学生没有表达的字段一律不要输出；表达含糊无法确定就输出 {}。",
        f"知识点目录（编号.标题）：{listing}\n学生的话：{msg}\n一行 JSON：",
    )
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _validated_tutoring_intent(data: dict, catalog: list[tuple[str, str]]) -> dict:
    """校验模型翻出的意图：越界或类型不对的字段直接丢弃（fail closed）。"""
    out: dict = {}
    if not isinstance(data, dict):
        return out
    total = len(catalog)
    raw_order = data.get("order")
    if isinstance(raw_order, list) and raw_order:
        picked: list[int] = []
        for item in raw_order:
            try:
                no = int(item)
            except (TypeError, ValueError):
                continue
            if 1 <= no <= total and no not in picked:
                picked.append(no)
        if picked:
            ids = [catalog[no - 1][0] for no in picked]
            rest = [kid for kid, _title in catalog if kid not in ids]
            out["order"] = ids + rest
    raw_ratings = data.get("self_ratings")
    if isinstance(raw_ratings, dict):
        ratings: dict[str, int] = {}
        for key, value in raw_ratings.items():
            try:
                no, stars = int(key), int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= no <= total and 1 <= stars <= 5:
                ratings[catalog[no - 1][0]] = stars
        if ratings:
            out["self_ratings"] = ratings
    raw_duration = data.get("duration_minutes")
    if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool):
        minutes = int(raw_duration)
        if 1 <= minutes <= 240:
            out["duration"] = minutes
    return out


def _tutoring_judge(question: dict, answer: str) -> tuple[str, str, dict]:
    """判定学生作答：correct / wrong / unclear / not_answer。

    **not_answer = 这句话不是在回答检测题**（想跳过/求助/改时间/结束等），
    此时额外返回 intent 槽位（同一行 JSON 里），由确定性处理器接管——
    意图理解进模型，状态变更仍在代码。

    返回 (verdict, note 一句话依据, extra={intent,kp_no,rating,minutes,order})。
    没有模型宁可 unclear——不瞎判，星级不动。判定是唯一入口，测试在此 mock。
    """
    if not llm_available():
        return "unclear", "", {}
    raw = llm_chat(
        "你是课堂里的 AI 辅导老师，正在判定学生对检测题的作答。"
        "只输出一行 JSON："
        "{\"verdict\": \"correct|wrong|unclear|not_answer\", "
        "\"intent\": \"...\", \"note\": \"一句话依据\"}。\n"
        "correct=答对了核心；wrong=答错或说反；unclear=在作答但太简短没法判定；\n"
        "not_answer=根本不是在回答这道题（想跳过、想问别的、求助、改复习时长、"
        "想结束复习等），此时 intent 从这些里选："
        "self_eval|kp_select|followup|help|time_change|end|skip|other，"
        "可带槽位 kp_no/rating/minutes/order（如 {\"intent\":\"self_eval\",\"kp_no\":2,\"rating\":3}）。",
        f"检测题：{question.get('question', '')}\n学生消息：{answer}\n"
        "请给出一行 JSON 判定：",
    )
    data = _tutoring_parse_json(raw)
    if not data:
        return "unclear", "", {}
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("correct", "wrong", "unclear", "not_answer"):
        return "unclear", "", {}
    extra = data if verdict == "not_answer" else {}
    return verdict, str(data.get("note", ""))[:120], extra


def _tutoring_parse_json(raw: str | None) -> dict | None:
    """从模型输出里抠一行 JSON；抠不到/不是对象 → None。"""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


_TUTORING_CLASSIFY_INTENTS = (
    "self_eval", "kp_select", "answer", "followup", "help",
    "time_change", "end", "skip", "other",
)


def _tutoring_classify_message(msg: str, catalog: list[tuple[str, str]],
                               has_question: bool) -> dict | None:
    """LLM 意图分类（兜底路径）：正则没认出的说法在这里判定。

    只影响「执行哪个确定性处理器」，状态变更本身仍在代码里做；
    槽位（kp_no/rating/minutes/order）在 teach 里过界校验。
    无模型/解析失败 → None，退回正则时代的兜底行为。
    """
    if not llm_available():
        return None
    listing = "、".join(f"{i}.{t}" for i, (_k, t) in enumerate(catalog, 1))
    raw = llm_chat(
        "你是课后辅导对话的意图分类器。学生正和 AI 老师一对一复习本节课知识点，"
        "判定他这条消息的意图，只输出一行 JSON，不要解释：\n"
        "{\"intent\": \"self_eval|kp_select|answer|followup|help|time_change|end|skip|other\""
        " 可带槽位：{\"intent\":\"self_eval\",\"kp_no\":2,\"rating\":3}、"
        "{\"intent\":\"kp_select\",\"order\":[2,1]}、{\"intent\":\"time_change\",\"minutes\":10}\n"
        "self_eval=给自己某知识点打 1-5 星；kp_select=指定复习顺序或想先复习哪个；"
        "answer=在回答当前检测题；followup=就内容追问；help=求助/要求讲解；"
        "time_change=调整复习时长；end=想结束本轮复习；skip=想跳过当前内容进入下一个；"
        "other=寒暄等其它。",
        ("当前有检测题在等他回答。\n" if has_question else "当前没有检测题。\n")
        + f"本节课知识点（编号.标题）：{listing}\n"
        + f"学生消息：{msg}\n请输出一行 JSON：",
    )
    data = _tutoring_parse_json(raw)
    if not data:
        return None
    if str(data.get("intent", "")) not in _TUTORING_CLASSIFY_INTENTS:
        return None
    return data


DEFAULT_TUTORING_RUBRIC = {
    "default_minutes": 15,
    "hinted_max_stars": 3,
    "stale_question_max_stars": 4,
    "rubric": {
        "1": "仅接触过概念：听过讲解，但说不出内容",
        "2": "能认出但不能自己讲：见到说法能判断对错，独立解释则说不清",
        "3": "提示下能做对：经追问或提示后能答对检测题",
        "4": "能独立做对已见题型：无需提示能答对，但尚未经未见过的新题确认",
        "5": "无提示独立做对未见新题：未见过、无提示、独立答对，并满足本条量规",
    },
}

_TUTORING_RUBRIC_CACHE: dict | None = None


def _tutoring_rubric() -> dict:
    """课后辅导量规与节奏配置：rules/TUTORING-RUBRIC.json，缺失/损坏回退内置默认。"""
    global _TUTORING_RUBRIC_CACHE
    if _TUTORING_RUBRIC_CACHE is not None:
        return _TUTORING_RUBRIC_CACHE
    loaded = dict(DEFAULT_TUTORING_RUBRIC)
    try:
        path = Path(__file__).resolve().parent / "rules" / "TUTORING-RUBRIC.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("default_minutes", "hinted_max_stars", "stale_question_max_stars"):
            if isinstance(data.get(key), int):
                loaded[key] = data[key]
        if isinstance(data.get("rubric"), dict):
            loaded["rubric"] = {
                str(k): str(v) for k, v in data["rubric"].items()}
    except (OSError, ValueError):
        pass
    _TUTORING_RUBRIC_CACHE = loaded
    return loaded


def tutoring_default_minutes() -> int:
    """默认规划时长（分钟）：env AGENT_TUTORING_DEFAULT_MINUTES 覆盖量规文件值。"""
    raw = (os.environ.get("AGENT_TUTORING_DEFAULT_MINUTES") or "").strip()
    if not raw:
        raw = str(_tutoring_rubric().get("default_minutes", 15))
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return 15


def _iso_plus_minutes(iso: str, minutes: float, scale: float = 1.0) -> str:
    """从 iso 起「minutes 分钟学生时间」后的墙钟时间戳。

    演练倍速（time_scale>1）下墙钟等比缩短，与全课计时约定一致；
    生产环境 scale=1，就是自然的分钟数。
    """
    return (datetime.fromisoformat(iso)
            + timedelta(minutes=minutes / max(scale, 0.001))).isoformat()


def _parse_tutoring_duration(msg: str) -> int | None:
    """「想复习 15 分钟」「再复习 10 分钟」：复习时长（分钟）。

    要求数字前有复习/学/打算之类的动词，避免把「还有 5 分钟吗」
    误判成改时长。
    """
    m = re.search(r"(?:复习|学习|学|看|聊|打算|花|用|再)\s*([0-9]+)\s*分钟", msg)
    if not m:
        return None
    minutes = int(m.group(1))
    return minutes if 1 <= minutes <= 240 else None


def _parse_tutoring_self_ratings(msg: str, catalog: list[tuple[str, str]],
                                 active_kid: str | None = None) -> dict[str, int]:
    """「2 我给自己 2 分」「第 3 个评 4 星」式自评：知识点编号 → 星级（1–5）。

    不带编号的「自评 3 分」记到当前正在复习的知识点上。
    自评只表达学生意愿，不进系统星级（kp_stars）。
    """
    ratings: dict[str, int] = {}
    n = len(catalog)
    for m in re.finditer(
            r"(?:第[\s，,、]*)?([0-9]+)[\s，,、]*(?:号|个)?[\s，,、]*(?:我[\s，,、]*)?(?:给[\s，,、]*)?自己\s*"
            r"(?:评\s*|打\s*)?(?:是\s*|为\s*)?([0-9]+)\s*[分星颗]",
            msg):
        no, stars = int(m.group(1)), int(m.group(2))
        if 1 <= no <= n and 1 <= stars <= 5:
            ratings[catalog[no - 1][0]] = stars
    for m in re.finditer(r"自评\s*(?:为\s*)?([0-9]+)\s*[分星颗]", msg):
        stars = int(m.group(1))
        if 1 <= stars <= 5 and active_kid:
            ratings.setdefault(active_kid, stars)
    return ratings


def tutoring_public(state: ClassroomState, now_iso: str | None = None,
                    time_scale: float = 1.0) -> dict:
    """/api/session/{sid}/state 的 tutoring 块：固定编号目录 + 复习顺序 + 时间预算。

    编号是开场消息里给学生的那套固定数字编号（目录序，1 起），
    前端掌握条照它渲染，不用自己再算。remaining_seconds 是学生时间
    （服务端时间戳换算，刷新/换设备不清零）。
    """
    catalog = _lesson_kp_catalog(state)
    no_of = {kid: i for i, (kid, _title) in enumerate(catalog, 1)}
    order = state.get("tutoring_order") or [kid for kid, _title in catalog]
    end = state.get("tutoring_planned_end_at")
    remaining = None
    if end and now_iso:
        delta = (datetime.fromisoformat(end)
                 - datetime.fromisoformat(now_iso)).total_seconds()
        remaining = max(0, round(delta * float(time_scale or 1.0)))
    question = state.get("tutoring_question")
    # 高亮以显式记录的「正在讲的知识点」为准；旧会话（升级前持久化的
    # state 没有这个键）回退用 挂起题的知识点，再退到顺序+游标推导。
    active = state.get("tutoring_active_kp")
    if not active and question:
        active = question.get("kp_id")
    current_no = None
    if active and active in no_of:
        current_no = no_of[active]
    elif active is None:
        cursor = state.get("tutoring_cursor", 0)
        if 0 <= cursor < len(order) and order[cursor] in no_of:
            current_no = no_of[order[cursor]]
    return {
        "knowledge_points": [
            {"no": i, "kp_id": kid, "title": title}
            for i, (kid, title) in enumerate(catalog, 1)
        ],
        "order": [no_of[kid] for kid in order if kid in no_of],
        "current_no": current_no,
        "self_ratings": {
            str(no_of[kid]): stars
            for kid, stars in (state.get("tutoring_self_ratings") or {}).items()
            if kid in no_of
        },
        "stars": {
            str(no_of[kid]): int(v)
            for kid, v in (state.get("tutoring_stars") or {}).items()
            if kid in no_of
        },
        "question": ({
            "kp_no": no_of[question["kp_id"]],
            "kp_id": question["kp_id"],
            "text": question.get("question", ""),
            "hint_given": bool(question.get("hint_given")),
            "was_fresh": bool(question.get("was_fresh", True)),
        } if question and question.get("kp_id") in no_of else None),
        "planned_minutes": int(state.get("tutoring_planned_minutes") or 0),
        "planned_end_at": end,
        "remaining_seconds": remaining,
        # 评分标准（量规）：掌握条的小图标悬停/聚焦/点击展示
        "rubric": _tutoring_rubric().get("rubric") or {},
    }


def knowledge_catalog_public(state: ClassroomState) -> list[dict]:
    """/state 的固定编号知识点目录（**任何阶段都在**）：下课页等展示用。

    与辅导目录同源（lesson_plan / learning_context 的知识点清单），
    各处展示不再读课时文件里的静态列表——那份清单和真实目录会漂移。
    """
    return [{"no": i, "kp_id": kid, "title": title}
            for i, (kid, title) in enumerate(_lesson_kp_catalog(state), 1)]


def tutoring_feedback_payload(state: ClassroomState,
                              trigger_text: str = "") -> tuple[dict, str]:
    """明确结束时生成完整反馈（确定性骨架，工单 05）。

    返回 (学生视角 payload, 教师视角摘要)。栏目结构为草稿
    （工单评论里标注待用户过目）：各知识点终值星级与证据、复习用时、
    答题统计、未完成检测、后续建议。
    """
    catalog = _lesson_kp_catalog(state)
    no_of = {kid: i for i, (kid, _t) in enumerate(catalog, 1)}
    # 反馈里的系统星 = 辅导作答证据星（课堂「已接触」基线不混入，
    # 那是学情导出的口径，不是辅导反馈的）
    stars = state.get("tutoring_stars") or {}
    ratings = state.get("tutoring_self_ratings") or {}
    evidence_by_kp: dict[str, list[str]] = {}
    for item in state.get("mastery_updates") or []:
        if item.get("source") == "tutoring":
            evidence_by_kp.setdefault(item.get("kp_id", ""), []).append(
                item.get("evidence") or "")
    kps = [{
        "no": no_of.get(kid), "kp_id": kid, "title": title,
        "system_stars": int(stars.get(kid, 0)),
        "self_rating": ratings.get(kid),
        "evidence": [e for e in evidence_by_kp.get(kid, []) if e],
    } for kid, title in catalog]
    stats = dict(state.get("tutoring_stats") or {})
    planned = int(state.get("tutoring_planned_minutes") or 0)
    end_at = state.get("tutoring_planned_end_at")
    remaining_minutes = 0.0
    if end_at:
        delta = (datetime.fromisoformat(end_at)
                 - datetime.fromisoformat(state["now"])).total_seconds()
        remaining_minutes = max(0.0, delta / 60 * float(state.get("time_scale") or 1.0))
    actual = max(0, planned - int(round(remaining_minutes)))
    weak = [k["title"] for k in kps if k["system_stars"] <= 2]
    strong = sum(1 for k in kps if k["system_stars"] >= 3)
    payload = {
        "schema": "tutoring-feedback/1",
        "trigger": (trigger_text or "").strip()[:60],
        "planned_minutes": planned,
        "actual_minutes": actual,
        "asked_questions": len(state.get("tutoring_asked") or []),
        "stats": stats,
        "knowledge_points": kps,
        "unfinished_question": (state.get("tutoring_question") or {}).get("question"),
        "advice": ("课后优先复习：" + "、".join(weak)) if weak
                  else "各知识点掌握均衡，保持练习。",
        "generated_at": state.get("now"),
    }
    teacher_summary = (
        f"课后辅导：复习约 {actual} 分钟，答题 "
        f"{len(state.get('tutoring_asked') or [])} 道"
        f"（对 {stats.get('correct', 0)} / 错 {stats.get('wrong', 0)}，"
        f"其中提示后答对 {stats.get('hinted_correct', 0)}）；"
        f"{len(kps)} 个知识点中 {strong} 个达 3 星以上"
        + (f"；薄弱点：{'、'.join(weak)}" if weak else "")
        + "。"
    )
    return payload, teacher_summary


def _tutoring_opening_skeleton(state: ClassroomState) -> str:
    """开场消息的确定性骨架：知识点固定编号列表 + 征询意愿（全部可省略）。"""
    catalog = _lesson_kp_catalog(state)
    if catalog:
        listing = "\n".join(f"{i}. {title}" for i, (_kid, title) in enumerate(catalog, 1))
        intro = f"本节课的知识点：\n{listing}"
    else:
        intro = "这节课没有登记知识点，我们就按刚才视频讲的内容来复习。"
    return (
        "视频全部看完啦！接下来是课后辅导：我围绕你自己的情况，"
        "把这节课的内容再过一遍。\n\n"
        f"{intro}\n\n"
        "你可以先告诉我（都可以省略，不说我就自己安排）：\n"
        "- 想按什么顺序复习，比如「先 2 再 1」；\n"
        "- 哪个编号的知识点还没听懂；\n"
        "- 给自己的掌握情况自评几颗星（1–5 星）；\n"
        "- 打算复习多长时间，比如「复习 15 分钟」。"
    )


def tutoring_opening(state: ClassroomState) -> tuple[str, bool]:
    """课后辅导的开场消息：骨架即全文，**不进模型**。

    开场是「视频完→辅导」切换轮的一部分，编号列表与征询项全是确定性
    交付；原先让模型润色会把切换拖慢 20–35 秒（平台态每轮还带一万多字
    课程上下文）。模型从学生第一条消息开始参与。编号列表照旧原文交付。
    """
    return _tutoring_opening_skeleton(state), False


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
    no_polish = False   # 安全关键文案（结束确认等）骨架直出，不让模型改写

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

    elif phase == "tutoring":
        # 工单 02：意愿解析（顺序/自评/时长）+ 七类消息分流，全在确定性骨架层；
        # LLM 只润色与答疑。确认类内容是硬性交付：模型缺席时骨架原文说给学生
        # （见下方 tutoring fallback）。
        updates["current_target"] = None
        updates["current_question"] = None
        if msg.strip():
            catalog = _lesson_kp_catalog(state)
            listing = "、".join(f"{i}. {t}" for i, (_kid, t) in enumerate(catalog, 1))
            title_of = {kid: t for kid, t in catalog}
            order = _parse_tutoring_order(msg, catalog)
            if order:
                updates["tutoring_order"] = order
                updates["tutoring_active_kp"] = order[0]
            active_order = order or state.get("tutoring_order") or []
            active = active_order[0] if active_order else (catalog[0][0] if catalog else "")
            title = title_of.get(active, "刚才视频的内容")
            new_ratings = _parse_tutoring_self_ratings(msg, catalog, active)
            if new_ratings:
                updates["tutoring_self_ratings"] = {
                    **(state.get("tutoring_self_ratings") or {}), **new_ratings,
                }
            duration = _parse_tutoring_duration(msg)
            if duration:
                updates["tutoring_planned_minutes"] = duration
                updates["tutoring_planned_end_at"] = _iso_plus_minutes(
                    state["now"], duration, float(state.get("time_scale") or 1.0))

            # ── 模型翻译官（工单 07）：正则没认出的意愿，让模型翻成结构化
            # 意图，骨架校验通过才写状态；不合法当没说。正则认出的字段优先，
            # 模型只补缺口；结束意愿不在此处触发（仍走正则 + 结束确认回合）。
            if llm_available() and (not order or not new_ratings or not duration):
                extra = _validated_tutoring_intent(
                    _tutoring_extract_intent_llm(msg, catalog), catalog)
                if extra.get("order") and not order:
                    order = extra["order"]
                    updates["tutoring_order"] = order
                    updates["tutoring_active_kp"] = order[0]
                if extra.get("self_ratings") and not new_ratings:
                    new_ratings = extra["self_ratings"]
                    updates["tutoring_self_ratings"] = {
                        **(state.get("tutoring_self_ratings") or {}), **new_ratings,
                    }
                if extra.get("duration") and not duration:
                    duration = extra["duration"]
                    updates["tutoring_planned_minutes"] = duration
                    updates["tutoring_planned_end_at"] = _iso_plus_minutes(
                        state["now"], duration, float(state.get("time_scale") or 1.0))
                # 模型补出了顺序时，当前聚焦的知识点跟着变（title 供确认文案用）
                if extra.get("order") and order:
                    active = order[0]
                    title = title_of.get(active, "刚才视频的内容")

            # 时间预算只改教学安排：到点在回复里加一句关照，绝不关会话。
            end_at = state.get("tutoring_planned_end_at")
            time_up = bool(end_at) and (
                datetime.fromisoformat(state["now"])
                >= datetime.fromisoformat(end_at))
            timeup_note = (
                "时间差不多到了——还有想再问的吗？没有的话说一声，我们就可以收尾。\n"
                if time_up else "")

            confirms: list[str] = []
            if order and len(order) > 1:
                head = "再".join(f"「{title_of[kid]}」" for kid in order[:2])
                confirms.append(f"好，就按你说的顺序：先{head}（其余按课件顺序）。")
            elif order:
                confirms.append(f"好，那就先复习「{title}」。")
            if new_ratings:
                rated = "、".join(
                    f"「{title_of.get(kid, kid)}」{stars} 星"
                    for kid, stars in new_ratings.items()
                )
                confirms.append(
                    f"你的自评我记下了（{rated}）——它代表你的感觉，"
                    "系统星级还是看你实际作答。"
                )
            if duration:
                confirms.append(
                    f"好，那就复习 {duration} 分钟——到点我不会赶你走，"
                    "只会问问你还想继续哪里。"
                )

            kind = (
                "end" if _TUTORING_END_PAT.search(msg)
                else "skip" if _TUTORING_SKIP_PAT.search(msg)
                else "time_change" if duration
                else "self_eval" if new_ratings
                else "kp_select" if order
                else "followup" if _TUTORING_QUES_PAT.search(msg)
                else "help" if _TUTORING_HELP_PAT.search(msg)
                else "answer"
            )

            # ── 结束确认回合（LLM 提议的结束需二次确认，防误杀）──
            # 肯定 → 置 confirmed 交 judge_advance 同回合下课（它在 teach 之后运行）；
            # 否定 → 清待确认标记，本轮只做安抚不再分类/判答。
            if bool(state.get("tutoring_end_confirm_pending")) and kind != "end":
                if _TUTORING_CONFIRM_PAT.fullmatch(msg):
                    return {"reply_text": "", "llm_used": False,
                            "attempts": state.get("attempts", 0),
                            "tutoring_end_confirm_pending": False,
                            "tutoring_end_confirmed": True}
                if _TUTORING_DECLINE_PAT.search(msg):
                    updates["tutoring_end_confirm_pending"] = False
                    kind = "declined_end"

            # ── 检测题机制（工单 03/04）：出题 → 判答 → 升星/追问讲解 → 换新题 → 推进 ──
            prev_question = state.get("tutoring_question")
            seen = list(state.get("tutoring_asked") or [])
            judged: dict | None = None
            judge_extra: dict = {}
            wrong_replaced = False
            stars = dict(state.get("kp_stars") or {})
            stats = dict(state.get("tutoring_stats") or {})
            if kind == "answer" and prev_question:
                verdict, _note, judge_extra = _tutoring_judge(prev_question, msg)
                kid = prev_question.get("kp_id") or ""
                if verdict == "correct":
                    stats["correct"] = int(stats.get("correct", 0)) + 1
                    if bool(prev_question.get("hint_given")):
                        stats["hinted_correct"] = int(stats.get("hinted_correct", 0)) + 1
                    updates["tutoring_stats"] = stats
                    hinted = bool(prev_question.get("hint_given"))
                    current = int(stars.get(kid, 0))
                    # 5 星门槛（量规）：有提示 ≤3；见过的题 ≤4；
                    # 只有「未见新题 + 无提示 + 独立答对」才可能到 5。
                    rub = _tutoring_rubric()
                    if hinted:
                        cap = int(rub.get("hinted_max_stars", 3))
                    elif not prev_question.get("was_fresh", True):
                        cap = int(rub.get("stale_question_max_stars", 4))
                    else:
                        cap = 5
                    stars[kid] = max(current, min(cap, current + 1))
                    updates["kp_stars"] = stars
                    # 辅导证据星独立累积，同受量规上限约束（掌握条/反馈只认作答挣来的星）
                    t_stars = dict(state.get("tutoring_stars") or {})
                    t_stars[kid] = min(cap, int(t_stars.get(kid, 0)) + 1)
                    updates["tutoring_stars"] = t_stars
                    updates["tutoring_question"] = None
                    updates["tutoring_cursor"] = (
                        0 if order else state.get("tutoring_cursor", 0)) + 1
                    # 证据条目走既有 mastery_updates 通道：平台态由会话层写
                    # student.knowledge_mastery（星级只升不降），demo 态进导出
                    updates["mastery_updates"] = list(state.get("mastery_updates") or []) + [{
                        "kp_id": kid,
                        "new_stars": stars[kid],
                        "new_status": STAR_STATUS.get(stars[kid], "未检测"),
                        "evidence": ("辅导检测题答对（有提示）" if hinted
                                     else "辅导检测题答对（无提示独立作答）"),
                        "source": "tutoring",
                    }]
                    judged = {"kp_id": kid, "verdict": "correct",
                              "hint_given": hinted,
                              "question": prev_question.get("question", ""),
                              "stars_after": stars[kid]}
                elif verdict == "wrong":
                    # 答错不降星、不换知识点。第一次错：同题标记提示、追问；
                    # 连续错：讲解并安排**未见过的新题**确认（方案：答错追问/讲解
                    # 之后安排无提示新题）。新题本身不带提示，答对按正常路径升星。
                    if int(prev_question.get("wrong_count", 0)) >= 1:
                        stats["wrong"] = int(stats.get("wrong", 0)) + 1
                        updates["tutoring_stats"] = stats
                        title_w = title_of.get(kid, "刚才视频的内容")
                        text, fresh = _tutoring_pick_question(title_w, seen)
                        updates["tutoring_question"] = {
                            "kp_id": kid, "question": text,
                            "asked_at": state.get("now"), "hint_given": False,
                            "was_fresh": fresh, "wrong_count": 0,
                        }
                        updates["tutoring_active_kp"] = kid
                        seen.append(text)
                        updates["tutoring_asked"] = list(seen)
                        wrong_replaced = True
                        judged = {"kp_id": kid, "verdict": "wrong", "hint_given": True,
                                  "question": prev_question.get("question", ""),
                                  "stars_after": stars.get(kid, 0)}
                    else:
                        stats["wrong"] = int(stats.get("wrong", 0)) + 1
                        updates["tutoring_stats"] = stats
                        carried = dict(prev_question)
                        carried["hint_given"] = True
                        carried["wrong_count"] = 1
                        updates["tutoring_question"] = carried
                        judged = {"kp_id": kid, "verdict": "wrong", "hint_given": True,
                                  "question": prev_question.get("question", ""),
                                  "stars_after": stars.get(kid, 0)}
                # unclear：不判、不记事件、不动状态
            updates["tutoring_last_judgement"] = judged

            # ── 意图兜底（LLM）：正则没认出的说法在这里分流 ──
            # 有挂起题时判答器在同一次调用里裁定 not_answer+intent（不加调用）；
            # 无挂起题时独立分类一次。意图只决定执行哪个确定性处理器；
            # 槽位过界一律忽略，退回答题兜底——LLM 永远不能发明状态。
            llm_intent: dict | None = None
            if kind == "answer" and judged is None:
                if prev_question:
                    llm_intent = judge_extra if judge_extra.get("intent") else None
                else:
                    llm_intent = _tutoring_classify_message(msg, catalog, False) or None
            if llm_intent:
                intent = str(llm_intent.get("intent", ""))
                if intent in ("skip", "followup", "help"):
                    kind = intent
                elif intent == "end":
                    kind = "end_confirm"
                elif intent == "time_change":
                    minutes = llm_intent.get("minutes")
                    if isinstance(minutes, int) and 1 <= minutes <= 240:
                        duration = minutes
                        updates["tutoring_planned_minutes"] = duration
                        updates["tutoring_planned_end_at"] = _iso_plus_minutes(
                            state["now"], duration, float(state.get("time_scale") or 1.0))
                        confirms.append(
                            f"好，那就复习 {duration} 分钟——到点我不会赶你走，"
                            "只会问问你还想继续哪里。")
                        kind = "time_change"
                elif intent == "self_eval":
                    no, rating = llm_intent.get("kp_no"), llm_intent.get("rating")
                    if (isinstance(no, int) and 1 <= no <= len(catalog)
                            and isinstance(rating, int) and 1 <= rating <= 5):
                        kid_r = catalog[no - 1][0]
                        updates["tutoring_self_ratings"] = {
                            **(state.get("tutoring_self_ratings") or {}), kid_r: rating}
                        confirms.append(
                            f"你的自评我记下了（「{title_of.get(kid_r, kid_r)}」{rating} 星）"
                            "——它代表你的感觉，系统星级还是看你实际作答。")
                        kind = "self_eval"
                elif intent == "kp_select":
                    nos = llm_intent.get("order")
                    if isinstance(nos, list):
                        ids = [catalog[n - 1][0] for n in nos
                               if isinstance(n, int) and 1 <= n <= len(catalog)
                               and catalog[n - 1][0] not in ids]
                        if ids:
                            order = ids + [k for k, _t in catalog if k not in ids]
                            updates["tutoring_order"] = order
                            updates["tutoring_active_kp"] = order[0]
                            head = "再".join(f"「{title_of.get(k, k)}」" for k in order[:2])
                            confirms.append(f"好，就按你说的顺序：先{head}（其余按课件顺序）。")
                            kind = "kp_select"
                # answer/other/槽位校验失败：维持答题兜底

            # 当前聚焦的知识点（本轮指定了顺序 → 游标归零；判对 → 已推进）
            order_now = order or state.get("tutoring_order") or [k for k, _t in catalog]
            cursor_now = updates.get("tutoring_cursor",
                                     0 if order else state.get("tutoring_cursor", 0))
            in_range = 0 <= cursor_now < len(order_now)
            active = order_now[cursor_now] if in_range else (
                order_now[-1] if order_now else "")
            title = title_of.get(active, "刚才视频的内容")

            def _ask_question() -> None:
                text, fresh = _tutoring_pick_question(title, seen)
                updates["tutoring_question"] = {
                    "kp_id": active,
                    "question": text,
                    "asked_at": state.get("now"),
                    "hint_given": False,
                    "was_fresh": fresh,
                    "wrong_count": 0,
                }
                updates["tutoring_active_kp"] = active
                seen.append(text)
                updates["tutoring_asked"] = list(seen)

            if judged and judged["verdict"] == "correct":
                if in_range:
                    _ask_question()
                    body = (
                        "答得漂亮——记你一星。我们接着看"
                        f"「{title}」：{updates['tutoring_question']['question']}"
                    )
                else:
                    updates["tutoring_active_kp"] = None
                    body = (
                        "这节课的知识点都过完了！还有想再问的吗？"
                        "没有的话说一声，我们就可以收尾。"
                    )
            elif judged and judged["verdict"] == "wrong":
                if wrong_replaced:
                    new_q = updates.get("tutoring_question") or {}
                    body = (
                        "我们先把这道放下，我把关键点给你捋一捋（听老师讲解）。"
                        f"换一道新题确认一下：{new_q.get('question', '')}"
                    )
                else:
                    body = (
                        "嗯，这个说法有问题，先别急着往下。我们退一步想："
                        f"「{title}」最关键的一点是什么？用自己的话再试一次。"
                    )
            elif kind == "answer" and prev_question:
                body = (
                    "我没能确定你的意思，再说详细一点——"
                    f"针对「{title}」的这题：{prev_question.get('question', '')}"
                )
            elif kind == "skip":
                # 推进指令（「下一阶段／下一个／跳过」）：直接跳到顺序中的
                # 下一个知识点出新题。被跳过的题留在已见清单里，回头再问
                # 也会换一道。这不是作答——不判答、不动星级。
                if in_range and cursor_now + 1 < len(order_now):
                    updates["tutoring_cursor"] = cursor_now + 1
                    next_kid = order_now[cursor_now + 1]
                    next_title = title_of.get(next_kid, "刚才视频的内容")
                    next_q, next_fresh = _tutoring_pick_question(next_title, seen)
                    updates["tutoring_question"] = {
                        "kp_id": next_kid, "question": next_q,
                        "asked_at": state.get("now"), "hint_given": False,
                        "was_fresh": next_fresh, "wrong_count": 0,
                    }
                    updates["tutoring_active_kp"] = next_kid
                    seen.append(next_q)
                    updates["tutoring_asked"] = list(seen)
                    body = (
                        f"好，「{title}」先放一放。我们看下一个"
                        f"「{next_title}」：{next_q}"
                    )
                else:
                    updates["tutoring_question"] = None
                    updates["tutoring_active_kp"] = None
                    body = (
                        "这节课的知识点都过完了！还有想再问的吗？"
                        "没有的话说一声，我们就可以收尾。"
                    )
            elif kind == "answer" or confirms:
                pending = prev_question
                if not pending:
                    _ask_question()
                    q_text = updates["tutoring_question"]["question"]
                else:
                    q_text = pending.get("question", "")
                body = "".join(confirms) + (
                    q_text if q_text
                    else f"我们先从「{title}」开始："
                         "你先说说对它的理解，我看看哪里需要补一补。"
                )
            elif kind == "declined_end":
                no_polish = True
                body = (
                    "好，那我们继续。"
                    + (f" 还是刚才这题：{prev_question.get('question', '')}"
                       if prev_question else "")
                )
            elif kind == "end_confirm":
                no_polish = True
                updates["tutoring_end_confirm_pending"] = True
                body = (
                    "要结束这轮复习吗？结束后我会给你生成完整的复习反馈，"
                    "之后随时可以回来继续。回复「结束」或「是」确认，想继续就直接说。"
                )
            elif kind == "end":
                # 结束的正式动作（生成反馈并入库）是工单 05 的活，这里只承接。
                body = (
                    f"好，那我们准备收尾。最后把「{title}」再快速过一遍；"
                    "确认要结束的时候再说一声。"
                )
            else:
                snippet = msg.strip().strip("？?。，,、")[:24]
                body = (
                    f"你提到的「{snippet}」正是复习「{title}」的好切入点："
                    "先说说你现在已经理解的部分，我从你卡住的地方讲起。"
                )
            plain = timeup_note + body

            pending_now = updates.get("tutoring_question", prev_question)
            order_text = "、".join(
                title_of.get(kid, kid) for kid in (order or order_now)
            ) or "按目录顺序"
            directive = (
                "课后辅导阶段，学生发了消息。先按已确认的安排回应，再回应这句本身。\n"
                f"本节课知识点（固定编号，不得增删、不得改号）：{listing}\n"
                f"已确认的复习顺序（从先到后）：{order_text}\n"
                + (f"本轮教学只围绕知识点「{title}」（学生指定顺序中的当前项）；"
                   "除非学生主动问到别的知识点，不要引入其他知识点的内容。\n"
                   if in_range else "")
                + (f"学生本轮更新了复习时长：{duration} 分钟，从这条消息时刻起算。\n"
                   if duration else "")
                + ("时间预算已到点：先温和地问他还想继续哪里，不催促结束。\n"
                   if time_up else "")
                + ("学生表达了结束意愿：确认后按结束流程收尾。\n"
                   if kind == "end" else "")
                + ("学生要求跳到下一个知识点：按确认后的推进措辞说，别再回到上一个。\n"
                   if kind == "skip" else "")
                + ("学生提出了问题或求助：直接回答或讲解，只依据本课已发布内容。\n"
                   if kind in ("followup", "help") else "")
                + (f"当前检测题（无模型时也要照问）：{pending_now.get('question', '')}\n"
                   if pending_now and pending_now.get("question") else "")
                + (f"学生刚刚答对了检测题（{'有提示' if judged['hint_given'] else '无提示'}），"
                   "已升星并进入下一个知识点。\n"
                   if judged and judged["verdict"] == "correct" else "")
                + ("学生刚刚答错了检测题，请针对他的错误具体追问或讲解。\n"
                   if judged and judged["verdict"] == "wrong" else "")
                + "讲解与提问都严格落在这份清单内；学生没说的安排由你自行决定。"
            )
        else:
            speak = False          # 心跳轮静默，辅导只回应学生

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

    # ── 第二层：LLM 只负责把指令变成自然语言（可失败；安全关键文案除外）──
    if llm_available() and not no_polish:
        polished = llm_polish(state, directive)
        if polished:
            updates["reply_text"] = polished.strip()
            updates["llm_used"] = True
            return updates

    updates["reply_text"] = NO_LLM_NOTICE if (not llm_available() and phase != "tutoring") else plain
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

    if phase == "tutoring":
        # 课后辅导没有时间出口：到点只改变教学安排，不因时间预算把学生踢出会话。
        # 唯一出口 = 学生明确结束（工单 05）：直接说结束，或到点关照后的确认
        # （「没有了」「可以了」这类短确认只在计划时间已过后算数）。外部事件
        # （下一环节/结束本节课）在上面已经判过，老师按钮仍然有效。
        msg = (state.get("student_message") or "").strip()
        # LLM 识别并经学生确认的结束（teach 本轮已置位；judge_advance 在
        # teach 之后运行，同回合生效），随切幕由 advance_stage 清零。
        if state.get("tutoring_end_confirmed"):
            return {"target_phase": "ending", "advance_reason": "学生确认结束课后辅导"}
        end_at = state.get("tutoring_planned_end_at")
        time_up = bool(end_at) and (
            datetime.fromisoformat(state["now"]) >= datetime.fromisoformat(end_at))
        # 到点后的短确认只在没有挂起检测题时才算结束——学生对着题答「好/行」
        # 是作答，不是确认下课。
        confirmed = (time_up and not state.get("tutoring_question")
                     and msg and re.fullmatch(
                         r"(?:没有[了]?|没了|不用了?|好了?|可以了?|行|嗯+)"
                         r"(?:[。！!，, ]*(?:没有[了]?|没了|不用了?|好了?|可以了?|行|嗯+))*"
                         r"[。！!，, ]*",
                         msg))
        if _TUTORING_END_PAT.search(msg) or (msg and confirmed):
            return {"target_phase": "ending", "advance_reason": "学生明确结束课后辅导"}
        return {"target_phase": None, "advance_reason": "课后辅导进行中，等待学生明确结束"}

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
    # 切进「课后辅导」说的是知识点编号开场（骨架定结构，LLM 只润色）。
    if nxt == "guided_learning" and stage_delivery(state) == "video":
        opening, gen = "", False
    elif nxt == "tutoring":
        opening, gen = tutoring_opening(state)
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
        # 结束确认标记是「一次性」的：切幕即消费，避免恢复辅导后被残留标记误下课
        "tutoring_end_confirm_pending": False,
        "tutoring_end_confirmed": False,
        "reply_text": (reply + ("\n\n" if reply and opening else "") + opening).strip(),
        "advance_reason": state.get("advance_reason"),
        "llm_used": gen,
    }
    if nxt == "tutoring":
        # 未报时长先按默认规划时长起算；学生随后报时长会按那条消息时刻重设。
        default_min = tutoring_default_minutes()
        out["tutoring_planned_minutes"] = default_min
        out["tutoring_planned_end_at"] = _iso_plus_minutes(
            now, default_min, float(state.get("time_scale") or 1.0))
        # 刚进辅导还没开始讲任何知识点：显式置空（高亮不亮）
        out["tutoring_active_kp"] = None
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
    segments = plan.get("segments", [])
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

def initial_state(session_id: str, student_id: str = "", lesson_id: str = "") -> dict:
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
        "tutoring_order": [],
        "tutoring_self_ratings": {},
        "tutoring_planned_minutes": 0,
        "tutoring_planned_end_at": None,
        "tutoring_cursor": 0,
        "tutoring_active_kp": None,
        "tutoring_stars": {},
        "tutoring_question": None,
        "tutoring_last_judgement": None,
        "tutoring_asked": [],
        "tutoring_stats": {},
        "tutoring_end_confirm_pending": False,
        "tutoring_end_confirmed": False,
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
