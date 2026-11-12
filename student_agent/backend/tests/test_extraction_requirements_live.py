"""Opt-in behavioral smoke cases through learning_points with a real provider.

Lexical checks target these concrete fixtures; they are not a general semantic
validator. Every output is retained for manual review, including assertion failures.
"""
import ast
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from openai import DefaultHttpxClient
import pytest

from backend.content import knowledge, lesson_content
from backend.content.context import classroom_materials
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT

ROOT = Path(__file__).resolve().parents[3]
CASES = {
    "independent_memory": ("HTTP响应状态码", "本节只要求记住两个HTTP响应状态码的含义：200表示请求成功；404表示请求的资源未找到。本课没有讲其他状态码或请求方法。"),
    "preserve_cause": ("为什么留一个空位", "循环队列中，队空时front等于rear。如果把所有位置都存满，rear绕回后也等于front，程序无法分清空和满。因此约定留一个空位，队满时(rear+1)%MAXQSIZE等于front，从而与队空区分。重点理解留一个空位为什么能区分空满。"),
    "independent_design": ("构造栈式行编辑方案", "本课教学生独立构造行编辑的栈处理方案。普通字符入栈，退格撤销最近输入的一个字符，整行撤销清空当前行。完成标准是这两种撤销分别产生正确结果。只处理当前行；本课未讲跨行撤销或重做。"),
}


def requirement_texts(points, *, design_only=False):
    texts = []
    for point in points:
        if design_only and point["type"] != "design":
            continue
        for key in ("requiredElements", "understandingPoints", "successCriteria"):
            texts.extend(point["details"].get(key, []))
    return texts


def check_case(case, points):
    texts = requirement_texts(points)
    if case == "independent_memory":
        assert any("200" in t and "404" not in t for t in texts), texts
        assert any("404" in t and "200" not in t for t in texts), texts
        assert not any("200" in t and "404" in t for t in texts), texts
        details = json.dumps([p["details"] for p in points], ensure_ascii=False)
        assert not any(term in details for term in ("rear", "链队列", "500", "POST")), details
    elif case == "preserve_cause":
        assert any(any(w in t for w in ("空位", "一格", "位置")) and "空" in t and "满" in t
                   and any(w in t for w in ("区分", "分辨", "混淆", "区别", "分清")) for t in texts), texts
    elif case == "independent_design":
        texts = requirement_texts(points, design_only=True)
        backspace = lambda t: any(w in t for w in ("退格", "最近", "单个", "一个字符"))
        clear = lambda t: any(w in t for w in ("清空", "整行", "所有字符"))
        assert any(backspace(t) and not clear(t) for t in texts), texts
        assert any(clear(t) and not backspace(t) for t in texts), texts
        assert not any(backspace(t) and clear(t) for t in texts), texts
    else:
        linked = [p for p in points if "链队列" in json.dumps({"title": p["title"], "details": p["details"]}, ensure_ascii=False)]
        texts = requirement_texts(linked)
        insertion = lambda t: any(w in t.lower() for w in ("rear", "队尾", "尾结点", "尾节点", "尾指针")) and any(w in t for w in ("插", "接", "追加"))
        capacity = lambda t: any(w in t for w in ("队满", "满队", "固定容量", "固定长度", "容量上限", "数组容量"))
        assert any(insertion(t) and not capacity(t) for t in texts), texts
        assert any(capacity(t) and not insertion(t) for t in texts), texts
        assert not any(insertion(t) and capacity(t) for t in texts), texts


@pytest.mark.skipif(os.environ.get("STUDENT_EXTRACTION_LIVE_VERIFICATION") != "1",
                    reason="Opt in to real provider extraction with STUDENT_EXTRACTION_LIVE_VERIFICATION=1")
@pytest.mark.parametrize("case", ["independent_memory", "preserve_cause", "independent_design", "real_lesson"])
def test_extracted_requirements_keep_independent_goals_separate_and_relationships_intact(case, monkeypatch):
    variant = os.environ.get("EXTRACTION_PROMPT_VARIANT", "current")
    assert variant in {"baseline", "current"}
    output = ROOT / "student_agent/docs/knowledge-extraction/validation/2026-11-10-requirement-splitting" / os.environ.get("EXTRACTION_VERIFICATION_RUN", variant) / (case + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), "Never overwrite a recorded provider run"
    if case == "real_lesson":
        source = json.loads((ROOT / ".runtime/typed-knowledge-live/source.json").read_text(encoding="utf-8"))
        materials = classroom_materials(source["scenes"])
    else:
        title, content = CASES[case]
        materials = [{"id": "fixture:" + case, "source": "published-classroom-scene", "title": title, "content": content}]
    prompt = KNOWLEDGE_EXTRACTION_PROMPT
    if variant == "baseline":
        original = subprocess.run(["git", "show", "HEAD:student_agent/backend/content/prompts.py"], cwd=ROOT,
                                  check=True, capture_output=True, encoding="utf-8").stdout
        assignment = next(n for n in ast.parse(original).body if isinstance(n, ast.Assign))
        prompt = ast.literal_eval(assignment.value.func.value).strip()
    report = {"case": case, "variant": variant, "productionWrites": False,
              "materialManifestHash": lesson_content.digest(materials), "materialCount": len(materials),
              "systemPrompt": prompt, "promptHash": hashlib.sha256(prompt.encode()).hexdigest(), "trace": []}
    original_send = DefaultHttpxClient.send
    provider_host = urlsplit(os.environ.get("STUDENT_AGENT_BASE_URL") or os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1").hostname

    def observe(self, request, **kwargs):
        if request.url.host != provider_host:
            return original_send(self, request, **kwargs)
        body = json.loads(request.content)
        # A/B differs only at the external system-message boundary. No response
        # injection, internal factory mock, or extra production model call.
        for message in body["messages"]:
            if message["role"] == "system":
                message["content"] = prompt
        headers = request.headers.copy()
        headers.pop("content-length", None)
        request = type(request)(request.method, request.url, headers=headers,
            content=json.dumps(body, ensure_ascii=False).encode(), extensions=request.extensions)
        entry = {"model": body.get("model"), "toolChoice": body.get("tool_choice"),
                 "feedbackMessages": [m for m in body["messages"] if m["role"] == "tool" or
                    (m["role"] == "user" and "materials" not in str(m.get("content")))]}
        report["trace"].append(entry)
        response = original_send(self, request, **kwargs)
        entry["httpStatus"] = response.status_code
        if response.status_code == 200:
            payload = response.json()
            message = payload["choices"][0]["message"]
            entry.update(content=message.get("content"), toolCalls=message.get("tool_calls", []), usage=payload.get("usage"))
        return response

    monkeypatch.setattr(DefaultHttpxClient, "send", observe)
    try:
        result = knowledge.learning_points(materials, "verification-course", "verification-lesson")
        report.update(status="extracted", **asdict(result))
        check_case(case, result.points)
        report["behaviorCheck"] = "passed_fixture_smoke_check"
    except AssertionError:
        report["behaviorCheck"] = "failed_fixture_smoke_check"
        raise
    except Exception as error:
        report.update(status="failed", errorType=type(error).__name__, code=getattr(error, "code", None))
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
