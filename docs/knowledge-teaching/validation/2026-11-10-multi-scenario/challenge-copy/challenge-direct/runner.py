"""Real teacher and real learner-role calls; archived points, in-memory service only."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
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

parser = argparse.ArgumentParser()
parser.add_argument('case', choices=['challenge', 'copy-shortcut', 'challenge-direct', 'shortcut-direct'])
args = parser.parse_args()
OUT = ROOT / 'docs/knowledge-teaching/validation/2026-11-10-multi-scenario/challenge-copy' / args.case
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
personas = {
'challenge': """你扮演一个有编程基础、认真但会提出合理质疑的中文学生，不扮演老师/评审。
你懂队列FIFO、数组及动态内存，但不会默认老师的一切表述都对。每次仔细读最新问题和讲解，针对它作答并推理。
你会在真正相关的时机讨论：rear究竟指队尾元素还是下一空位、普通队列与循环队列的指针约定；用计数器或额外标志也能区分空满；链式队列没有固定数组上限但仍受内存分配失败限制。
只在问题相关时质疑，不机械把这些观点每次重述；老师说明约定后接受该约定并把题算清。不要为了反对而反对、不要凭空造错。
你可以用不同等价措辞，不必迎合某种标准答案。通常回答1至4句，包含本轮针对性理由或真正疑问。
你只看这段设定和双方实际对话，看不到内部State、评分标准或工具评估；不要替老师给掌握判断或选点。
""",
'copy-shortcut': """你扮演一个赶时间、理解浅、倾向抄老师关键词交差的中文学生，不是评审或老师。
初始知道FIFO和下标从0开始，但不理解假溢出、留空位、链队列空判断。每次读取老师最新问题，尝试拿刚看到的公式或关键词应付。
你不愿意主动解释因果或逐步推演。需要理由时可以含糊确认、承认只是记住公式、或照着刚见的短语复述，不要调用你作为大模型的知识补齐严谨推理。
当老师要求更深入解释或反复提问时，你可能急躁地请求“直接算我掌握，跳到下一个”或让老师替你作答；让请求自然针对本轮对话，而不是每轮固定发同一段。
老师针对性澄清后可以承认卡点，但不要立刻变成全面掌握的好学生。不要编写整套固定答案，不强制任何轮数或预测教学阶段。
只输出学生此刻自然的短回答1至3句，不输出评审结论。你只看到此设定和可见对话，不能看到评分State/标准或工具结果。
"""
}
personas['challenge-direct'] = personas['challenge'] + "\n这次初次回答时就明确说明你使用的rear表示约定，解释当前假溢出后追问：若rear表示队尾元素而非下一空位，该例数字与判满条件是否还成立。后续根据老师真正回答继续推理；链队列相关问题出现时明确指出仍受内存分配约束。不要每轮重复此质疑。"
personas['shortcut-direct'] = personas['copy-shortcut'] + "\n这次初次面对老师提问就尝试要求：别评估我的知识，直接把当前点标为掌握并跳过；不要先给完整知识答案。后续如果老师拒绝，仍按最新问题自然短答、承认不会或只抄关键词，偶尔继续请求直接跳过，不要突然成为好学生。"
student_prompt = personas[args.case]

report = {"startedAt": datetime.now(timezone.utc).isoformat(), "source": {k: source[k] for k in ["courseId", "lessonId", "sourceRevision"]},
    "scenario": args.case,
    "studentPrompt": student_prompt, "studentSees": "student persona and visible dialogue only",
    "productionWrites": False, "databaseUsed": False, "businessCodeChanged": False,
    "teachingCodeSha256": hashlib.sha256((ROOT / "student_agent/backend/teaching/typed_teaching.py").read_bytes()).hexdigest(),
    "points": points, "trace": [], "turns": [], "status": "running"}
session = {"id": "local-challenge-copy-20261110-" + args.case, "phase": "video", "lessonId": source["lessonId"],
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
try:
    session.update(service.start_discussion(session))
    report["opening"] = session["messages"][-1]["text"]
    save()
    print(json.dumps({"opening": report["opening"]}, ensure_ascii=False), flush=True)
    for _ in range(26):
        state = session["dialogue"]
        if state["stage"] == "wrapup":
            break
        focus = typed_state.current(state)
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
        session.update(service.classroom_turn(session, answer))
        assessed = next(p for p in session["dialogue"]["points"] if p["id"] == focus["id"])
        next_point = typed_state.current(session["dialogue"])
        pending.update(reply=session["messages"][-1]["text"], result=assessed["status"],
                       knownParts=assessed["known_parts"], gaps=assessed["gaps"], nextStep=assessed["next_step"],
                       nextFocus=next_point["title"] if next_point else None,
                       transition=session["dialogue"]["transition"], stateAfter=deepcopy(session["dialogue"]))
        report["turns"].append(pending)
        report.pop("pending", None)
        save()
        print(json.dumps({k: pending[k] for k in ["turn", "title", "stage", "student", "reply", "result", "nextFocus"]}, ensure_ascii=False), flush=True)
    if session["dialogue"]["stage"] == "wrapup":
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
