"""落盘：把整理产物写到规定位置。

- 知识点 → 更新 rules/KNOWLEDGE-BASE.md（合并）+ 写 lesson-data/<course>/<lesson>/知识点.md
- 课程目标 → lesson-data/<course>/<lesson>/本节课目标.md
- 字幕 → lesson-data/<course>/<lesson>/字幕.md

原子写沿用 orchestrator/agent.save_lesson() 的「先写 .tmp 再 os.replace」模式；
文件名白名单与 orchestrator/agent.safe_lesson_id() 同规则（此处独立实现，避免 ingest
依赖 langgraph / 整个编排器）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ingest.extract import KP_FIELDS

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_BASE_PATH = ROOT / "rules" / "KNOWLEDGE-BASE.md"
LESSON_DATA_DIR = ROOT / "lesson-data"

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _safe_id(value: str) -> str:
    """course_id / lesson_id 安全校验（与 orchestrator/agent.safe_lesson_id 同规则）。"""
    if not _ID_RE.match(value or ""):
        raise ValueError(
            f"非法 id：{value!r}（只允许字母数字与 . _ -，以字母数字开头，最长 64 字符）"
        )
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise ValueError(f"非法 id：{value!r}（Windows 保留设备名）")
    return value


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _format_kp_block(kp: dict) -> str:
    """单个知识点 → 一个 md 块（字段序与 rules/KNOWLEDGE-BASE.md 一致）。

    标题后空一行，与现有 KNOWLEDGE-BASE.md 的样例块格式对齐。
    """
    head = f"{kp.get('kp_id', '')} {kp.get('title', '')}".strip() or "知识点"
    lines = [f"## {head}", ""]
    for field in KP_FIELDS:
        lines.append(f"- {field}: {str(kp.get(field) or '').strip()}")
    return "\n".join(lines)


def format_knowledge_points_md(points: list[dict]) -> str:
    """知识点列表 → 知识点.md 全文。"""
    return "\n\n".join(_format_kp_block(kp) for kp in points) + "\n"


def update_knowledge_base(points: list[dict]) -> None:
    """合并知识点进 rules/KNOWLEDGE-BASE.md：已存在则替换整块，否则追加。

    用「拆分前缀 + 重建」而不是正则就地替换 —— 就地替换会在块边界上吞掉换行，
    把下一个 `## KP-xxx` 标题粘连到上一个块的字段行尾（实测踩过）。
    """
    text = (
        KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
        if KNOWLEDGE_BASE_PATH.is_file() else ""
    )

    # 现有 KP 块：按文件顺序拆成 [(kp_id, 块原文)]；前缀 = 第一个 KP 块之前的内容
    kp_re = re.compile(
        r"^##\s+(KP-\d+)\b[^\n]*\n.*?(?=^##\s+KP-\d+\b|\Z)", re.M | re.S
    )
    first = kp_re.search(text)
    prefix = text[: first.start()] if first else text
    blocks: list[tuple[str, str]] = [
        (m.group(1), m.group(0)) for m in kp_re.finditer(text)
    ]

    # 合并：保留现有顺序，被更新的替换、新的追加到末尾
    block_map = {kp_id: block for kp_id, block in blocks}
    for kp in points:
        kp_id = kp.get("kp_id")
        if not kp_id:
            continue
        block_map[kp_id] = _format_kp_block(kp)

    chunks = [prefix.rstrip("\n")]
    chunks += [block.rstrip("\n") for block in block_map.values()]
    _atomic_write(KNOWLEDGE_BASE_PATH, "\n\n".join(chunks) + "\n")


def write_lesson_data(
    course_id: str,
    lesson_id: str,
    points: list[dict],
    goals: list[str],
    transcript: str,
) -> str:
    """写 lesson-data/<course>/<lesson>/ 三文件，返回目录相对路径。"""
    course_id = _safe_id(course_id)
    lesson_id = _safe_id(lesson_id)
    lesson_dir = LESSON_DATA_DIR / course_id / lesson_id
    lesson_dir.mkdir(parents=True, exist_ok=True)

    _atomic_write(lesson_dir / "知识点.md", format_knowledge_points_md(points))

    goal_lines = ["# 本节课目标"] + [f"- {g}" for g in goals]
    _atomic_write(lesson_dir / "本节课目标.md", "\n".join(goal_lines) + "\n")

    _atomic_write(lesson_dir / "字幕.md", f"# 字幕\n\n{transcript}\n")

    return f"lesson-data/{course_id}/{lesson_id}/"


def write_lesson_plan(course_id: str, lesson_id: str, plan: dict) -> str:
    """写 lesson-data/<course>/<lesson>/lesson-plan.json，返回相对路径。

    这是 ingest 的第四样产物（课时计划：总时长 + 阶段 + 各阶段时长），
    schema 与编排器课时定义一致，编排器经 load_lesson 的扫描兜底读取。
    """
    course_id = _safe_id(course_id)
    lesson_id = _safe_id(lesson_id)
    lesson_dir = LESSON_DATA_DIR / course_id / lesson_id
    lesson_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        lesson_dir / "lesson-plan.json",
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
    )
    return f"lesson-data/{course_id}/{lesson_id}/lesson-plan.json"
