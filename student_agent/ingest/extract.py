"""清洗 / 提取：把原始脏数据（大纲 + 字幕）整理成三样产物。

- 字幕：去杂不简化 —— 剥时间轴、序号、HTML 标签、头部噪音，保留完整正文。
- 知识点 / 目标：按大纲标题锚点抽取。

假设大纲是带层级标题的结构化文本（docx / 大纲导出）。若实际是自由文本，
`extract_knowledge_points` / `extract_goals` 预留 LLM 抽取扩展点（离线、不影响上课）。
"""

from __future__ import annotations

import re

# 知识点字段（与 rules/KNOWLEDGE-BASE.md 一致，便于未来复用 agent._parse_kb_questions 解析）
KP_FIELDS = (
    "定义", "检测问题", "掌握表现",
    "为什么这样设计", "如何实现", "解决什么实际问题", "关联学科",
)

# 字幕噪音
_TIMELINE_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?\s*-->\s*"
    r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[,.]\d{1,3})?\s*$"
)
_INDEX_RE = re.compile(r"^\s*\d+\s*$")
_TAG_RE = re.compile(r"<[^>]+>")
_SUBTITLE_HEADERS = {"WEBVTT", "KIND: CAPTIONS", "LANGUAGE: ZH", "LANGUAGE: EN"}


def clean_transcript(raw: str) -> str:
    """字幕去杂不简化：剥时间轴行、序号行、HTML 标签、头部噪音，合并为完整文本。"""
    lines: list[str] = []
    for line in (raw or "").splitlines():
        line = _TAG_RE.sub("", line).strip()
        if not line:
            continue
        if _TIMELINE_RE.match(line):
            continue
        if _INDEX_RE.match(line):
            continue
        if line.upper() in _SUBTITLE_HEADERS:
            continue
        lines.append(line)
    return "\n".join(lines)


def _strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _has_any_field(kp: dict) -> bool:
    return any(f in kp for f in KP_FIELDS)


def extract_knowledge_points(syllabus: str) -> list[dict]:
    """从大纲抽取知识点列表。

    规则：按 `## KP-xxx 标题` 锚点分段（与 rules/KNOWLEDGE-BASE.md 同款），
    逐段抽 `- 字段: 值`。抽取失败返回空列表。
    """
    text = _strip_code_fences(syllabus or "")
    out: list[dict] = []
    cur: dict | None = None

    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^#{2,3}\s*(KP-\d+)\s*(.*)$", stripped)
        if m:
            if cur is not None and _has_any_field(cur):
                out.append(cur)
            cur = {"kp_id": m.group(1), "title": m.group(2).strip()}
            continue
        if cur is not None:
            fm = re.match(r"-\s*([^\s:：]+)\s*[:：]\s*(.*)", stripped)
            if fm and fm.group(1).strip() in KP_FIELDS:
                cur[fm.group(1).strip()] = fm.group(2).strip()

    if cur is not None and _has_any_field(cur):
        out.append(cur)
    return out


_GOAL_HEADERS = ("教学目标", "课程目标", "学习目标", "本节课目标")


def extract_goals(syllabus: str) -> list[str]:
    """从大纲抽取课程目标列表（按「教学目标/课程目标/学习目标」锚点）。"""
    text = _strip_code_fences(syllabus or "")
    out: list[str] = []
    in_goals = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m_head = re.match(r"^#{1,4}\s*(.+)$", stripped)
        if m_head:
            in_goals = any(h in m_head.group(1) for h in _GOAL_HEADERS)
            continue
        if in_goals:
            m_item = re.match(r"^[-*]\s+(.+)", stripped) or re.match(r"^\d+[.、]\s*(.+)", stripped)
            if m_item:
                out.append(m_item.group(1).strip())
    return out


_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:分钟|min(?:utes)?)", re.I)


def extract_duration(syllabus: str) -> int | None:
    """从大纲抽取课时总时长（分钟）。读不到返回 None（调用方默认 40 分钟）。

    只认「数字 + 分钟/min」的写法（如“45 分钟”“45min”），且取 0~600 之间的合理值。
    更聪明的抽取（自由文本/上下文理解）留给规划 AI 扩展点，这里保持确定性、离线可跑。
    """
    for m in _DURATION_RE.finditer(syllabus or ""):
        minutes = round(float(m.group(1)))
        if 0 < minutes < 600:
            return minutes
    return None
