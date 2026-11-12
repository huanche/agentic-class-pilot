"""Real teacher and real learner-role calls; archived points, in-memory service only."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.content.knowledge_schema import compatibility_text
from backend.infrastructure import model
from backend.teaching import service, typed_state

CASE = sys.argv[1]
MODE = "fault_retry" if CASE == "fault_retry_v2" else CASE
assert MODE in {"lifecycle", "fault_retry"}
OUT = ROOT / "docs/knowledge-teaching/validation/2026-11-10-multi-scenario/lifecycle-fault" / CASE
OUT.mkdir(parents=True, exist_ok=True)
assert not (OUT / "run.json").exists(), "Do not overwrite an actual trial"
config = {}
for base in [ROOT, Path("E:/LMS系统参考/项目/agentic-class-pilot-running")]:
    for name in ["student_agent/.env.local", "platform/.env"]:
        path = base / name
        if path.is_file():
            for key, value in dotenv_values(path, interpolate=False, encoding="utf-8-sig").items():
                if value is not None:
                    config.setdefault(key, value)
for new, old in [("STUDENT_AGENT_API_KEY", "AGENT_LLM_API_KEY"), ("STUDENT_AGENT_BASE_URL", "AGENT_LLM_BASE_URL"), ("STUDENT_AGENT_MODEL", "AGENT_LLM_MODEL")]:
    if not config.get(new) and config.get(old):
        config[new] = config[old]
for key in ["STUDENT_AGENT_API_KEY", "STUDENT_AGENT_BASE_URL", "STUDENT_AGENT_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]:
    if config.get(key):
        os.environ.setdefault(key, config[key])
os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"

source = json.loads((ROOT / "docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json").read_text(encoding="utf-8"))
titles = ["循环队列与假溢出的解决", "链队列的实现要点"]
points = [deepcopy(p) for p in source["points"] if p["title"] in titles]
assert [p["title"] for p in points] == titles
for p in points:
    p["content"] = p["description"] = compatibility_text(p)
student_prompt = """你现在扮演一个刚学队列的中文学生，不扮演老师或评审。
你的初始知识：知道队列先进先出、数组下标从0开始；对front/rear、假溢出、循环队列和链队列空判断还不熟。
只根据自己上述初始知识、这场对话中老师已经讲过的内容和自己的逐步推理作答。
每次读老师最新的具体问题，针对那个问题回答。不会时明确说卡在哪里，允许提出具体疑问；
老师讲解后可以理解、推断、改正原来的想法，并用自己的话说明理由。不要机械复述旧答案或只说“懂了”。
不要凭你作为大模型的全部知识一次性背出尚未学过的标准答案，不要故意犯错或刻意拖延轮数。
不要替老师评价掌握、选知识点、编老师下一句；只输出学生此刻自然的回答，通常1至4句话。
你看不到老师的内部State、掌握标准或工具评估，不猜测这些内容。
"""
report = {"startedAt": datetime.now(timezone.utc).isoformat(), "source": {k: source[k] for k in ["courseId", "lessonId", "sourceRevision"]},
    "scenario": MODE + "; responsive learner; service entry only; not HTTP or DB end-to-end", "events": [],
    "studentPrompt": student_prompt, "studentSees": "student persona and visible dialogue only",
    "productionWrites": False, "databaseUsed": False, "businessCodeChanged": False,
    "teachingCodeSha256": hashlib.sha256((ROOT / "student_agent/backend/teaching/typed_teaching.py").read_bytes()).hexdigest(),
    "points": points, "trace": [], "turns": [], "status": "running"}
session = {"id": "local-responsive-student-20261110", "phase": "video", "lessonId": source["lessonId"],
    "videoRevision": source["sourceRevision"], "messages": [], "courses": [], "preparation": "ready",
    "dialogue": service.new_dialogue(points)}
pending = {}
active_calls = {}

def save():
    report["session"] = session
    (OUT / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

class Capture(BaseCallbackHandler):
    def __init__(self, role):
        self.role = role
    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        entry = {"role": self.role, "turn": len(report["turns"]) + 1,
                 "messages": [m.model_dump(include={"type", "content", "tool_calls", "tool_call_id", "name"}) for m in messages[0]]}
        report["trace"].append(entry)
        active_calls[str(run_id)] = entry
        save()
    def on_llm_end(self, response, *, run_id, **kwargs):
        msg = response.generations[0][0].message
        active_calls[str(run_id)].update(content=msg.content, toolCalls=msg.tool_calls, usage=msg.usage_metadata)
        save()
    def on_llm_error(self, error, *, run_id, **kwargs):
        active_calls[str(run_id)].update(errorType=type(error).__name__, httpStatus=getattr(error, "status_code", None))
        save()

teacher = model.teaching_model()
learner = model.teaching_model()
teacher.callbacks, learner.callbacks = [Capture("teacher")], [Capture("learner")]
report["teacherModel"], report["learnerModel"] = teacher.model_name, learner.model_name
model.teaching_model = lambda: teacher
if MODE == "fault_retry":
    import httpx
    from openai import DefaultHttpxClient
    original_send = DefaultHttpxClient.send
    fault = {"armed": False}
    def injected_send(self, request, **kwargs):
        try:
            body = json.loads(request.content)
        except Exception:
            body = {}
        if fault["armed"] and body.get("tool_choice") == "none":
            fault["armed"] = False
            report["events"].append({"kind": "controlled_transport_timeout", "note": "one final generation request blocked before provider; not a naturally observed outage"})
            raise httpx.ReadTimeout("controlled teaching trial timeout", request=request)
        return original_send(self, request, **kwargs)
    DefaultHttpxClient.send = injected_send
try:
    session.update(service.start_discussion(session))
    report["opening"] = session["messages"][-1]["text"]
    save()
    print(json.dumps({"opening": report["opening"]}, ensure_ascii=False), flush=True)
    if MODE == "fault_retry":
        fault["armed"] = True
    for _ in range(26):
        state = session["dialogue"]
        after_class = session["phase"] == "done"
        if typed_state.current(state, after_class=after_class) is None:
            break
        focus = typed_state.current(state, after_class=after_class)
        learner_messages = [SystemMessage(content=student_prompt)] + [
            HumanMessage(content=m["text"]) if m["role"] == "assistant" else AIMessage(content=m["text"])
            for m in session["messages"]]
        answer = str(learner.invoke(learner_messages, timeout=45).content).strip()
        assert answer, "Empty learner response"
        pending = {"turn": len(report["turns"]) + 1, "title": focus["title"], "pointId": focus["id"],
                   "stage": state["stage"], "latestTeacher": session["messages"][-1]["text"],
                   "student": answer, "stateBefore": deepcopy(state)}
        report["pending"] = pending
        save()
        turn_service = service.postclass_turn if after_class else service.classroom_turn
        before_session = deepcopy(session)
        try:
            changes = turn_service(session, answer)
        except Exception as failure:
            if MODE != "fault_retry" or not report["events"] or report["events"][-1]["kind"] != "controlled_transport_timeout":
                raise
            unchanged = session == before_session
            report["events"].append({"kind": "retry_same_answer", "failureType": type(failure).__name__, "inputSessionUnchanged": unchanged})
            assert unchanged
            changes = turn_service(session, answer)
            assessed_retry = next(p for p in changes["dialogue"]["points"] if p["id"] == focus["id"])
            assert len(assessed_retry["assessment_history"]) == len(focus["assessment_history"]) + 1
            report["events"][-1]["exactlyOneAssessmentAfterRetry"] = True
        session.update(changes)
        assessed = next(p for p in session["dialogue"]["points"] if p["id"] == focus["id"])
        next_point = typed_state.current(session["dialogue"], after_class=after_class)
        pending.update(reply=session["messages"][-1]["text"], result=assessed["status"],
                       knownParts=assessed["known_parts"], gaps=assessed["gaps"], nextStep=assessed["next_step"],
                       nextFocus=next_point["title"] if next_point else None,
                       transition=session["dialogue"]["transition"], stateAfter=deepcopy(session["dialogue"]))
        report["turns"].append(pending)
        report.pop("pending", None)
        if MODE == "lifecycle" and len(report["turns"]) == 1:
            before_roundtrip = deepcopy(session)
            session = json.loads(json.dumps(session, ensure_ascii=False))
            assert session == before_roundtrip
            report["events"].append({"kind": "serialize_restore", "stateEqual": True})
            session.update(service.finish(session))
            report["events"].append({"kind": "early_finish", "feedback": deepcopy(session["feedback"])})
            session.update(service.start_postclass(session))
            before_pause = deepcopy(session["dialogue"])
            old_point = typed_state.current(before_pause, after_class=True)
            session.update(service.finish(session))
            assert session["postclassStage"] == "paused"
            session = json.loads(json.dumps(session, ensure_ascii=False))
            session.update(service.start_postclass(session))
            new_point = typed_state.current(session["dialogue"], after_class=True)
            same_task = old_point["id"] == new_point["id"] and old_point["task_question"] == new_point["task_question"]
            same_assessments = old_point["assessment_history"] == new_point["assessment_history"]
            report["events"].append({"kind": "postclass_pause_resume", "sameTask": same_task, "sameAssessments": same_assessments})
            assert same_task and same_assessments
        save()
        print(json.dumps({k: pending[k] for k in ["turn", "title", "stage", "student", "reply", "result", "nextFocus"]}, ensure_ascii=False), flush=True)
    if session.get("postclassStage") == "completed":
        report.update(status="completed", feedback=session["feedback"])
    elif session["dialogue"]["stage"] == "wrapup":
        session.update(service.finish(session))
        report.update(status="completed", feedback=session["feedback"])
    else:
        report["status"] = "runner_safety_limit"
except Exception as error:
    report.update(status="failed", errorType=type(error).__name__)
    if isinstance(error, (ValueError, TimeoutError)):
        report["error"] = str(error)
    raise
finally:
    save()
    print(json.dumps({"status": report["status"], "turns": len(report["turns"]), "calls": len(report["trace"])}, ensure_ascii=False), flush=True)
