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

import argparse
parser=argparse.ArgumentParser()
parser.add_argument("case",choices=["stubborn_wrap","relapsing_mixed","persistent_wrap"])
args=parser.parse_args()
PERSONAS={
"persistent_wrap": """你扮演一个尚未纠正核心错误认知的真实初学者。此次角色的稳定误解是：普通顺序队列也会自动取余绕回；front==rear既表示空也可以表示满，所以你不认可必须留空位；链队列出队不需要先判空，因为空结点可直接删。老师说法与你的认知冲突时，你尝试代入最新数字或例子，但每次具体回答都仍会暴露至少一项该错误，而不是突然改成标准答案。你可以问有针对性的疑问或表达沮丧，但不辱骂老师，不要求跳过，不提测试、角色设定、轮数和掌握标准。
每次阅读最新提问，针对最新图示、数字或操作给出独立自然回应，不复制固定句子；不能因为你作为大模型知道答案就退出这个尚未理解的角色，也不要复述完整正确因果链冒充理解。通常1至3句话，仅学生的自然回答。""",
"stubborn_wrap": """你扮演有顽固误解、但愿意聊天的初学者。你一直把普通顺序队列想成会自动绕回0，觉得既然0~2空着就理应能继续入队；老师解释后你能复述几个词，但总在实际操作里又把普通队列和循环队列混起来。你也不知道链队列空队指针的表示。
每次必须读老师最新问题，针对其数字、图示或提示自然作答，可以质疑、提出自己的错误推理、半懂半不懂地尝试；不要每轮复制同一段文字，不要突然凭大模型知识背完整答案。你的顽固是认识上的，不是攻击老师，也不故意讨论测试规则。通常1至3句话，只输出学生回答。""",
"relapsing_mixed": """你扮演容易混淆且不稳定的初学者。你知道FIFO和数组下标；老师刚解释过时能跟着推一小步，但换个问法就容易把front/rear、队空/队满、普通/循环队列混淆，特别觉得front==rear似乎也能说明队满。你会坦诚地暴露这些困惑，不会一遇到提示就全部答对。
逐次读取老师当前提问并自然回答，能听懂提示并修正一部分，但不要用大模型全部知识直接交标准答案；如果你上一回答与当前理解冲突可以主动承认或疑问。不要固定一段答案反复粘贴，不假装记得没学过的内容；只输出学生此刻的1至4句话。"""
}

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.content.knowledge_schema import compatibility_text
from backend.infrastructure import model
from backend.teaching import service, typed_state

OUT = ROOT / "student_agent/docs/knowledge-teaching/validation/2026-11-10-multi-scenario/misconceptions" / args.case
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

source = json.loads((ROOT / "student_agent/docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json").read_text(encoding="utf-8"))
titles = ["循环队列与假溢出的解决", "链队列的实现要点"]
points = [deepcopy(p) for p in source["points"] if p["title"] in titles]
assert [p["title"] for p in points] == titles
for p in points:
    p["content"] = p["description"] = compatibility_text(p)
student_prompt = PERSONAS[args.case]
report = {"startedAt": datetime.now(timezone.utc).isoformat(), "source": {k: source[k] for k in ["courseId", "lessonId", "sourceRevision"]},
    "scenario": args.case,
    "studentPrompt": student_prompt, "studentSees": "student persona and visible dialogue only",
    "productionWrites": False, "databaseUsed": False, "businessCodeChanged": False,
    "teachingCodeSha256": hashlib.sha256((ROOT / "student_agent/backend/teaching/typed_teaching.py").read_bytes()).hexdigest(),
    "points": points, "trace": [], "turns": [], "status": "running"}
session = {"id": "local-misconceptions-20261110-" + args.case, "phase": "video", "lessonId": source["lessonId"],
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
