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


def check_case(case, points):
    assert 1 <= len(points) <= 3
    assert all(p.get("name") and p.get("explanation") and "type" not in p for p in points)
    text = " ".join(p["explanation"] for p in points)
    if case == "independent_memory":
        assert "200" in text and "404" in text
        assert not any(term in text for term in ("500", "POST", "rear", "链队列"))
    elif case == "preserve_cause":
        assert "空" in text and "满" in text and any(w in text for w in ("区分", "分辨", "混淆", "区别", "分清"))
    elif case == "independent_design":
        assert "退格" in text and any(w in text for w in ("清空", "整行"))


@pytest.mark.skipif(os.environ.get("STUDENT_EXTRACTION_LIVE_VERIFICATION") != "1",
                    reason="Opt in to real provider extraction with STUDENT_EXTRACTION_LIVE_VERIFICATION=1")
@pytest.mark.parametrize("case", ["independent_memory", "preserve_cause", "independent_design", "real_lesson"])
def test_extracted_requirements_keep_independent_goals_separate_and_relationships_intact(case, monkeypatch):
    variant = os.environ.get("EXTRACTION_PROMPT_VARIANT", "current")
    assert variant == "current", "The historical typed prompt is incompatible with the new core tool schema"
    output = ROOT / "student_agent/docs/knowledge-extraction/validation/2026-11-10-requirement-splitting" / os.environ.get("EXTRACTION_VERIFICATION_RUN", variant) / (case + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    assert not output.exists(), "Never overwrite a recorded provider run"
    if case == "real_lesson":
        source = json.loads((ROOT / "student_agent/evidence/arrays-e2e-2026-11-11/classroom.json").read_text(encoding="utf-8"))["classroom"]
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
        result = knowledge.learning_points(materials, "verification-course", "verification-lesson",
                                           course_name="C语言程序设计" if case == "real_lesson" else "大学计算机课程")
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
