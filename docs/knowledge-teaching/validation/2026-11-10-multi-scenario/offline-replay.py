"""Replay captured provider outputs through real teaching service, no network."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import httpx
from langchain_openai import ChatOpenAI

root = Path.cwd()
sys.path.insert(0, str(root / "student_agent"))
from backend.infrastructure import model
from backend.teaching import service, typed_teaching

os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"
path = root / "docs/knowledge-teaching/validation/2026-11-10-multi-scenario/challenge-copy/challenge/run.json"
record = json.loads(path.read_text(encoding="utf-8"))

def replay(state, messages, answer, responses):
    packets = iter(responses)
    def transport(request):
        saved = next(packets)
        calls = saved.get("toolCalls", [])
        message = {"role": "assistant", "content": saved.get("content")}
        if calls:
            message["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                "name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}} for c in calls]
        return httpx.Response(200, json={"id": "captured-replay", "object": "chat.completion", "created": 0,
            "model": "offline", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if calls else "stop"}]})
    base = deepcopy(record["session"])
    base.update(dialogue=deepcopy(state), messages=deepcopy(messages), phase="discussion")
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        offline = ChatOpenAI(model="offline", api_key="offline-captured-replay", base_url="https://offline.test/v1",
                             max_retries=0, http_client=client)
        model.teaching_model = lambda: offline
        return service.classroom_turn(base, answer)

turn = record["turns"][0]
assessment = record["trace"][2]["toolCalls"][0]["args"]["assessment"]
result = replay(turn["stateBefore"], [{"role": "assistant", "text": record["opening"], "phase": "recall"}],
                turn["student"], record["trace"][2:4])
point = result["dialogue"]["points"][0]
checks = {"remaining_gaps_should_not_disappear": not (assessment["gaps"] and point["status"] == "mastered" and not point["gaps"])}
print(json.dumps({"case": "mastered_with_gaps", "modelGapCount": len(assessment["gaps"]),
    "appliedStatus": point["status"], "appliedGaps": point["gaps"], "transition": result["dialogue"]["transition"]}, ensure_ascii=False))
pending = record["pending"]
try:
    replay(pending["stateBefore"], record["session"]["messages"], pending["student"], record["trace"][-2:])
    checks["captured_final_reply_should_be_readable"] = True
except Exception as error:
    chain = []
    cause = error
    while cause:
        chain.append({"type": type(cause).__name__, "message": str(cause)})
        cause = cause.__cause__
    print(json.dumps({"case": "captured_plain_summary", "offlineProviderStatus": 200, "errors": chain}, ensure_ascii=False))
    checks["captured_final_reply_should_be_readable"] = False
print(json.dumps(checks, ensure_ascii=False))
if "--probe" in sys.argv:
    accepted = typed_teaching.Assessment.model_validate(assessment)
    modified = deepcopy(record["trace"][2:4])
    modified[0]["toolCalls"][0]["args"]["assessment"]["result"] = "partial"
    control = replay(turn["stateBefore"], [{"role": "assistant", "text": record["opening"], "phase": "recall"}],
                     turn["student"], modified)
    print(json.dumps({"probe": "only_change_result_to_partial", "originalSchemaAcceptedContradiction": accepted.result == "mastered" and bool(accepted.gaps),
        "status": control["dialogue"]["points"][0]["status"], "gaps": control["dialogue"]["points"][0]["gaps"],
        "transition": control["dialogue"]["transition"]}, ensure_ascii=False))
    wrapped = deepcopy(record["trace"][-2:])
    wrapped[-1]["content"] = json.dumps({"text": wrapped[-1]["content"], "question": "", "assistance": "none"}, ensure_ascii=False)
    control = replay(pending["stateBefore"], record["session"]["messages"], pending["student"], wrapped)
    print(json.dumps({"probe": "only_wrap_same_summary_as_required_json", "serviceReturned": True,
        "sameVisibleText": control["messages"][-1]["text"] == record["trace"][-1]["content"],
        "stage": control["dialogue"]["stage"]}, ensure_ascii=False))
else:
    assert all(checks.values()), "Captured defects reproduced offline; no model/network calls"
