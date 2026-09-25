"""课时计划（lesson-plan）生成：总时长 → 视频时长 → 剩余时长 → 阶段分配。

ingest（课前整理老师资料）的一步，产出 `lesson-data/<course>/<lesson>/lesson-plan.json`，
schema 与编排器消费的课时定义一致（stages / total_minutes / advance_policy）。

- 总时长：从大纲抽（`extract.extract_duration`），读不到默认 40 分钟。
- 视频时长：**暂定**，先当显式输入（默认 0 = 占位），等视频接入后再填。
- 阶段分配：优先走规划 AI（`PLANNER_LLM_*`，OpenAI 兼容端点）；没配或失败走确定性规则。
- 每个非视频阶段 ≥ 2 分钟（`min_stage_minutes`）。
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
NON_VIDEO_STAGES = ("recap_discussion", "deep_inquiry", "class_discussion")
_ADVANCE_WHEN = {
    "recap_discussion": "either",
    "deep_inquiry": "either",
    "class_discussion": "budget",
}
_STAGE_LABELS = {
    "recap_discussion": "复述阶段",
    "deep_inquiry": "深层探究阶段",
    "class_discussion": "全班讨论阶段",
}


def planner_llm_available() -> bool:
    return bool(
        os.environ.get("PLANNER_LLM_BASE_URL")
        and os.environ.get("PLANNER_LLM_API_KEY")
        and os.environ.get("PLANNER_LLM_MODEL")
    )


def planner_llm_chat(system: str, user: str) -> str | None:
    """调规划 AI（OpenAI 兼容 /chat/completions）。失败返回 None → 走确定性规则。"""
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


def _distribute(total: int, n: int) -> list[int]:
    """把 total 分钟均分到 n 个阶段，每个至少 MIN_STAGE_MINUTES；余数往前补。"""
    if n <= 0 or total < n * MIN_STAGE_MINUTES:
        return []
    shares = [MIN_STAGE_MINUTES] * n
    for i in range(total - n * MIN_STAGE_MINUTES):
        shares[i % n] += 1
    return shares


def _video_stage(video: int) -> dict:
    return {"id": "guided_learning", "enabled": True, "delivery": "video",
            "minutes": video, "advance_when": "either"}


def _deterministic_stages(total: int, video: int) -> list[dict]:
    video = min(max(0, video), total)
    remaining = total - video
    n = len(NON_VIDEO_STAGES)
    while n > 0 and remaining < n * MIN_STAGE_MINUTES:
        n -= 1
    shares = _distribute(remaining, n) if n else []
    stages = [_video_stage(video)]
    for i in range(n):
        cid = NON_VIDEO_STAGES[i]
        stages.append({"id": cid, "enabled": True, "minutes": shares[i],
                       "advance_when": _ADVANCE_WHEN[cid]})
    for cid in NON_VIDEO_STAGES[n:]:
        stages.append({"id": cid, "enabled": False, "minutes": 0,
                       "advance_when": _ADVANCE_WHEN[cid]})
    return stages


def _ai_stages(total: int, video: int, syllabus: str) -> list[dict] | None:
    """调规划 AI 决定非视频阶段（要不要复述等 + 各阶段分钟）。失败返回 None。"""
    if not planner_llm_available():
        return None
    video = min(max(0, video), total)
    remaining = total - video
    if remaining <= 0:
        return None
    labels = "、".join(f"{cid}（{_STAGE_LABELS[cid]}）" for cid in NON_VIDEO_STAGES)
    system = (
        "你是课程编排规划器。根据一节课的总时长与视频时长，决定这节课需要哪些非视频阶段、"
        "各阶段几分钟。只输出一个 JSON 对象，不要解释、不要代码围栏。"
    )
    user = (
        f"总时长 {total} 分钟，视频 {video} 分钟，剩余 {remaining} 分钟要分给非视频阶段。\n"
        f"可选阶段：{labels}。\n"
        f"规则：每个启用阶段 ≥ {MIN_STAGE_MINUTES} 分钟；启用阶段时长之和正好等于 {remaining}；"
        f"可自行决定是否需要复述（recap_discussion）等；阶段 id 只能从可选里挑。\n"
        f"输出形如：{{\"stages\":[{{\"id\":\"recap_discussion\",\"minutes\":9}}]}}。\n"
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

    used: dict[str, int] = {}
    for item in chosen:
        if not isinstance(item, dict):
            return None
        cid = item.get("id")
        mins = item.get("minutes")
        if cid not in NON_VIDEO_STAGES or not isinstance(mins, (int, float)):
            return None
        used[cid] = max(MIN_STAGE_MINUTES, int(round(mins)))
    if sum(used.values()) != remaining:
        return None

    stages = [_video_stage(video)]
    for cid in NON_VIDEO_STAGES:
        if cid in used:
            stages.append({"id": cid, "enabled": True, "minutes": used[cid],
                           "advance_when": _ADVANCE_WHEN[cid]})
        else:
            stages.append({"id": cid, "enabled": False, "minutes": 0,
                           "advance_when": _ADVANCE_WHEN[cid]})
    return stages


def build_plan(*, course_id: str, lesson_id: str, lesson_title: str = "",
               course: str = "", total_minutes: int | None = None,
               video_minutes: int = 0, syllabus: str = "") -> dict:
    """生成一份 lesson-plan（schema 对齐编排器课时定义）。"""
    total = int(total_minutes) if total_minutes is not None else DEFAULT_TOTAL_MINUTES
    stages = _ai_stages(total, video_minutes, syllabus) or _deterministic_stages(total, video_minutes)
    return {
        "lesson_id": lesson_id,
        "lesson_title": lesson_title or lesson_id,
        "course_id": course_id,
        "course": course or course_id,
        "total_minutes": total,
        "stages": stages,
        "segments": [],  # TODO: 视频段落（等视频时长/分段信息到位后再填）
        "advance_policy": {
            "on_budget_exhausted": "wrap_up",
            "on_evidence_reached": "advance",
            "min_stage_minutes": MIN_STAGE_MINUTES,
            "max_stage_overrun_minutes": MAX_STAGE_OVERRUN_MINUTES,
        },
    }
