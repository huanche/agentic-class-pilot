"""课时计划（lesson-plan）生成：时间写死（总时长 40，复述 / 深层探究各 5），阶段取舍优先走规划 AI。

ingest（课前整理老师资料）的一步，产出 `lesson-data/<course>/<lesson>/lesson-plan.json`，
schema 与编排器消费的课时定义一致（stages / total_minutes / advance_policy）。

- 总时长：写死 40 分钟（不读大纲时长）。
- 视频时长：视频阶段 minutes 沿用 video_minutes（默认 0 = 占位），视频尚未接入。
- 非视频阶段分钟：写死 —— 复述 5 分钟、深层探究 5 分钟。
- 非视频阶段取舍：优先走规划 AI（`PLANNER_LLM_*`，OpenAI 兼容端点）决定要不要复述/深探；
  没配或失败则默认都要（复述 5 + 深层探究 5）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """读仓库根的 .env.local / .env（若存在），写入 os.environ。

    与 orchestrator/agent._load_dotenv 同规则：只在变量尚未设置时写入，
    保证命令行传入的环境变量优先级更高。ingest 不 import 编排器，故此处独立实现。
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

DEFAULT_TOTAL_MINUTES = 40
MIN_STAGE_MINUTES = 2
MAX_STAGE_OVERRUN_MINUTES = 3

# 非视频阶段：顺序即启用优先级（AI 可自行决定要不要某个阶段，比如复述）
NON_VIDEO_STAGES = ("recap_discussion", "deep_inquiry")
_ADVANCE_WHEN = {
    "recap_discussion": "either",
    "deep_inquiry": "either",
}
_STAGE_LABELS = {
    "recap_discussion": "复述阶段",
    "deep_inquiry": "深层探究阶段",
}

# 写死：复述 / 深层探究各 5 分钟（分钟不交给规划 AI，视频尚未接入）。
FIXED_RECAP_MINUTES = 5
FIXED_DEEP_INQUIRY_MINUTES = 5
_FIXED_MINUTES = {
    "recap_discussion": FIXED_RECAP_MINUTES,
    "deep_inquiry": FIXED_DEEP_INQUIRY_MINUTES,
}


def planner_llm_available() -> bool:
    return bool(
        os.environ.get("PLANNER_LLM_BASE_URL")
        and os.environ.get("PLANNER_LLM_API_KEY")
        and os.environ.get("PLANNER_LLM_MODEL")
    )


def planner_llm_chat(system: str, user: str) -> str | None:
    """调规划 AI（OpenAI 兼容 /chat/completions）。失败返回 None → 走默认规则。"""
    base = os.environ.get("PLANNER_LLM_BASE_URL")
    key = os.environ.get("PLANNER_LLM_API_KEY")
    model = os.environ.get("PLANNER_LLM_MODEL")
    if not (base and key and model):
        return None
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
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        # 读出响应体，拿到具体原因（如余额不足 / 限流 / 模型不存在）
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        print(f"[规划 AI 调用失败] HTTP {e.code}: {body or e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[规划 AI 调用失败] {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _video_stage(video: int) -> dict:
    return {"id": "guided_learning", "enabled": True, "delivery": "video",
            "minutes": video, "advance_when": "either"}


def _deterministic_stages(video: int) -> list[dict]:
    """默认规则：复述 5 分钟 + 深层探究 5 分钟（都要，分钟写死）。"""
    return [
        _video_stage(video),
        {"id": "recap_discussion", "enabled": True,
         "minutes": FIXED_RECAP_MINUTES, "advance_when": "either"},
        {"id": "deep_inquiry", "enabled": True,
         "minutes": FIXED_DEEP_INQUIRY_MINUTES, "advance_when": "either"},
    ]


def _ai_stages(video: int, syllabus: str) -> list[dict] | None:
    """调规划 AI 决定需要哪些非视频阶段（要不要复述等）。分钟写死，不交给 AI。失败返回 None。"""
    if not planner_llm_available():
        return None
    labels = "、".join(f"{cid}（{_STAGE_LABELS[cid]}）" for cid in NON_VIDEO_STAGES)
    system = (
        "你是课程编排规划器。根据一节课的大纲，决定这节课需要哪些非视频阶段。"
        "只输出一个 JSON 对象，不要解释、不要代码围栏。"
    )
    user = (
        f"可选阶段：{labels}。\n"
        f"规则：每个阶段的时长已写死（复述 5 分钟、深层探究 5 分钟），你只决定需要哪些阶段，不输出分钟。\n"
        f"输出形如：{{\"stages\":[{{\"id\":\"recap_discussion\"}},{{\"id\":\"deep_inquiry\"}}]}}。\n"
        f"参考大纲（截断）：\n{syllabus[:2000]}"
    )
    raw = planner_llm_chat(system, user)
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    chosen = data.get("stages") if isinstance(data, dict) else None
    if not isinstance(chosen, list) or not chosen:
        return None

    enabled: set[str] = set()
    for item in chosen:
        if not isinstance(item, dict):
            return None
        cid = item.get("id")
        if cid in NON_VIDEO_STAGES:
            enabled.add(cid)
    if not enabled:
        return None

    stages = [_video_stage(video)]
    for cid in NON_VIDEO_STAGES:
        if cid in enabled:
            stages.append({"id": cid, "enabled": True, "minutes": _FIXED_MINUTES[cid],
                           "advance_when": _ADVANCE_WHEN[cid]})
        else:
            stages.append({"id": cid, "enabled": False, "minutes": 0,
                           "advance_when": _ADVANCE_WHEN[cid]})
    return stages


def build_plan(*, course_id: str, lesson_id: str, lesson_title: str = "",
               course: str = "", video_minutes: int = 0, syllabus: str = "") -> dict:
    """生成一份 lesson-plan（schema 对齐编排器课时定义）。

    时间写死：总时长 40 分钟，复述 5 分钟、深层探究 5 分钟。
    阶段取舍优先走规划 AI（整理老师上下文），没配或失败则复述 + 深探都要。
    """
    stages = _ai_stages(video_minutes, syllabus) or _deterministic_stages(video_minutes)
    return {
        "lesson_id": lesson_id,
        "lesson_title": lesson_title or lesson_id,
        "course_id": course_id,
        "course": course or course_id,
        "total_minutes": DEFAULT_TOTAL_MINUTES,
        "stages": stages,
        "segments": [],  # TODO: 视频段落（等视频时长/分段信息到位后再填）
        "advance_policy": {
            "on_budget_exhausted": "wrap_up",
            "on_evidence_reached": "advance",
            "min_stage_minutes": MIN_STAGE_MINUTES,
            "max_stage_overrun_minutes": MAX_STAGE_OVERRUN_MINUTES,
        },
    }
