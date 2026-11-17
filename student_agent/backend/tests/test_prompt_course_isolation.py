"""Capture real Agent requests for unrelated lessons, including tool schemas."""
import json
import ast
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from backend.teaching import typed_state, typed_teaching
from backend.infrastructure import model
from test_typed_knowledge import ScriptedModel


class CaptureModel(ScriptedModel):
    schemas: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.schemas.extend(convert_to_openai_tool(tool) for tool in tools)
        return super().bind_tools(tools, **kwargs)


FOREIGN = ("栈", "rear", "队列", "入队", "数组", "下标", "1、3、5、7、9")


@pytest.mark.parametrize("kind,details", [
    ("memory", {"statement": "节拍的名称", "requiredElements": ["二拍子", "三拍子"]}),
    ("concept", {"explanation": "节拍组织强弱关系", "understandingPoints": ["强弱关系"]}),
    ("design", {"capability": "创作两小节旋律", "constraints": [], "successCriteria": ["符合指定节拍"]}),
])
@pytest.mark.parametrize("after_class", [False, True])
def test_unrelated_lesson_requests_do_not_contain_computing_examples(monkeypatch, kind, details, after_class):
    state = typed_state.initial([{"id": "music", "title": "音乐节拍", "type": kind, "details": details}])
    state["student_text"] = "请解释当前内容"
    packet = AIMessage(content="", tool_calls=[{"name": "submit_current_assessment", "id": "a",
        "args": {"intent": "question", "assessment": None,
                 "observation": {"help_quote": state["student_text"]}}}])
    client = CaptureModel(responses=[packet, AIMessage(content="我们来看当前节拍。")])
    monkeypatch.setattr(model, "teaching_model", lambda: client)
    typed_teaching.run(state, after_class=after_class)
    assert len(client.seen) == 2
    payload = json.dumps({"messages": [[m.content for m in batch] for batch in client.seen],
                          "tools": client.schemas}, ensure_ascii=False)
    assert "音乐节拍" in payload  # Real course content must remain available.
    assert "请解释当前内容" in payload
    leaked = [term for term in FOREIGN if term in payload]
    assert not leaked, f"Unrelated course content in actual model requests: {leaked}"


def test_backend_instruction_literals_have_no_known_course_examples():
    # Also cover dormant compatibility prompts and extraction tool descriptions.
    root = Path(__file__).resolve().parents[1]
    leaks = []
    for folder in (root / "teaching", root / "content"):
        for path in folder.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for term in FOREIGN:
                        if term in node.value:
                            leaks.append(f"{path.name}:{node.lineno}: {term}")
    assert not leaks, leaks
