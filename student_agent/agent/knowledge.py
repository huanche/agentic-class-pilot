"""Extract assessable concepts from teacher material, with exact source evidence."""
from __future__ import annotations

import hashlib
import json

from .graph import _completion, _json_object
from .prompts import KNOWLEDGE_EXTRACTION_PROMPT

CURRICULUM_VERSION = 6


def learning_points(materials: list[dict]) -> list[dict]:
    if not any(item.get("source") == "published-classroom-scene" for item in materials):
        return []
    raw = _completion(KNOWLEDGE_EXTRACTION_PROMPT, json.dumps(
        {"materials": [{"id": p["id"], "source": p["source"],
                        "title": p["title"], "content": p["content"]}
                       for p in materials]}, ensure_ascii=False))
    return validated_points(_json_object(raw), materials)


def validated_points(result: dict, materials: list[dict]) -> list[dict]:
    sources = {item["id"]: item for item in materials}
    if not isinstance(result.get("points"), list):
        raise ValueError("知识点提取结果格式不正确")
    points = []
    seen = set()
    for item in result["points"]:
        if not isinstance(item, dict):
            raise ValueError("知识点格式不正确")
        title = item.get("title")
        evidence = item.get("evidence")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("知识点名称不正确")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("知识点缺少视频原文依据")
        quotes = []
        source_ids = []
        for reference in evidence:
            if not isinstance(reference, dict):
                raise ValueError("知识点依据格式不正确")
            source = sources.get(reference.get("sourceId"))
            quote = reference.get("quote")
            if (not source or source.get("source") != "published-classroom-scene"
                    or not isinstance(quote, str) or not quote.strip()
                    or quote not in source["content"]):
                raise ValueError("知识点依据无法在当前视频原文中找到")
            quotes.append(quote.strip())
            source_ids.append(source["id"])
        title = title.strip()
        if not any(title in quote for quote in quotes):
            raise ValueError("知识点名称无法在视频原文依据中找到")
        if not any(len(quote) >= len(title) + 8 for quote in quotes):
            raise ValueError("视频原文不足以解释知识点")
        if title in seen:
            continue
        seen.add(title)
        content = "\n\n".join(dict.fromkeys(quotes))
        identity = json.dumps([title, sorted(set(source_ids))], ensure_ascii=False)
        points.append({
            "id": "concept:" + hashlib.sha256(identity.encode()).hexdigest()[:20],
            "title": title, "content": content, "description": content,
            "source": "published-classroom-scene",
            "sourceIds": list(dict.fromkeys(source_ids)),
        })
    return points
