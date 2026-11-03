"""Collect the exact scenes shown by the current lesson player."""
from __future__ import annotations

import re
from html import unescape


def classroom_materials(scenes: list[dict]) -> list[dict]:
    materials = []
    for index, scene in enumerate(sorted(scenes, key=lambda item: int(item.get("order") or 1)), 1):
        visible = scene.get("visibleText") or []
        if not visible:
            content = scene.get("content") or {}
            canvas = (content.get("canvas") or {}) if isinstance(content, dict) else {}
            visible = [unescape(re.sub(r"<[^>]*>", " ", str(element.get("content") or ""))).strip()
                       for element in canvas.get("elements") or []
                       if isinstance(element, dict) and element.get("type") == "text"]
        if isinstance(visible, str):
            visible = [visible]
        speech = [str(action.get("text") or "").strip() for action in scene.get("actions") or []
                  if isinstance(action, dict) and action.get("type") == "speech"]
        parts = ["画面文字：" + "；".join(part for part in visible if part)] if any(visible) else []
        if any(speech):
            parts.append("讲解旁白：" + " ".join(part for part in speech if part))
        if parts:
            materials.append({"id": f"scene:{scene.get('id') or index}",
                              "title": str(scene.get("title") or f"第 {index} 段内容"),
                              "content": "\n".join(parts)[:6000],
                              "source": "published-classroom-scene"})
    return materials


def lesson_points(context: dict, lesson_id: str) -> list[dict]:
    lesson = next((item for item in context.get("lessons") or []
                   if str(item.get("id")) == lesson_id), None)
    return classroom_materials(((lesson or {}).get("classroom") or {}).get("scenes") or [])
