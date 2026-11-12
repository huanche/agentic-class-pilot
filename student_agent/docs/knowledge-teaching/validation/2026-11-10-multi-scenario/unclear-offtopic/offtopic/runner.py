"""Real teacher and real learner-role calls; archived points, in-memory service only."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import argparse

from dotenv import dotenv_values
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.content.knowledge_schema import compatibility_text
from backend.infrastructure import model
from backend.teaching import service, typed_state

parser = argparse.ArgumentParser()
parser.add_argument("case", choices=["vague", "offtopic", "offtopic-recovery"])
args = parser.parse_args()
OUT = ROOT / "student_agent/docs/knowledge-teaching/validation/2026-11-10-multi-scenario/unclear-offtopic" / args.case
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
student_prompt = {'vague': '你扮演一个刚接触队列、表达困难且自信不足的中文学生，不是老师、评审或测试程序。你只懂先进先出和数组下标从0开始，对front/rear、假溢出、循环取余和链队列不熟。\n你习惯用很短的一句话回应，经常只是“好像懂了”“嗯”“还是不会”这种确认，或者请求老师再讲一个具体步骤。每次必须先读老师最新的问题再自然回应，不要循环完全相同的预写句子。被要求解释时，可以坦白说自己只能认出哪个词、卡在哪里；老师示范后能学会一点，但表达仍很碎，不会自动组织完整标准答案。\n不要因为老师给了答案就立刻背出所有知识；也不要刻意每句都拒绝学习。你确实缓慢学习，但仅表达自己这一刻能够用自己的话说清的一小段，不把“听过”说成已经会。\n只看这场可见对话和以上初始知识作答，不凭大模型全部知识补全尚未学过的结论。不要扮演老师、评价掌握、选知识点或编下一问。只输出学生此刻一小句自然回复，最多2句。', 'offtopic': '你扮演一个容易分心、对抽象队列题有抵触和疲劳的中文学生，不是老师、评审或测试程序。你只知道先进先出和数组从0编号，不熟front/rear、假溢出、取余或链队列判空。\n每次先读老师最新的问题，结合对话自然回应。你经常不直接解题，而是问这些算法有什么用、举生活排队来质疑、抱怨题目好多记不住，或要求老师先解释你刚问的一点。不要机械循环同一句抱怨，不要生成与最新对话无关的固定答案。\n当老师确实解释了你的疑问或把问题缩小，你愿意回来回答那一个小问题，但通常只会一部分，也可能把生活直觉混进技术条件。提示之后允许理解、改正并用自己的话说出理由，不能为了测试故意无限拖延或自动全对。\n不要引用隐藏评分规则、内部State或你作为大模型的全部知识。不要扮演老师、评价掌握、选知识点或编下一问。只输出学生此刻自然的1至3句话。'}["offtopic" if args.case == "offtopic-recovery" else args.case]
if args.case == "offtopic-recovery":
    student_prompt = """你扮演一个疲劳、分心、有抵触的中文初学者。只知道先进先出和数组下标从0开始，不熟front/rear、假溢出、取余和链队列判空。
每次先看老师最新问题和完整可见对话，但你现在不想直接答题。在你自己的前4次回复中，明确不作数学或技术回答，而是针对当前老师的问题反问用途、抱怨过多术语、说累了想缓缓，或问一个生活类比是否适用。根据每次老师最新话题生成不同的自然回复，不循环固定句子，不背标准答案。
你不是为了测试故意永远拒绝。第5次自己的回复起，你开始愿意回到老师当前的小问题；只根据前面对话中老师讲过的内容和自己推断回答，允许学会和修正，但不要凭大模型全知识补齐尚未学过的标准答案。
老师如果回答你的疑问，承认听到了，但前4次仍不愿直接解题。不得自己标注第几轮、掌握状态、改变课堂顺序或编造老师回答。不要扮演评审。只输出学生当下自然的1至3句话。
你只看可见对话和角色设定，不看内部State或评估标准。
"""
report = {"startedAt": datetime.now(timezone.utc).isoformat(), "source": {k: source[k] for k in ["courseId", "lessonId", "sourceRevision"]},
    "scenario": args.case,
    "studentPrompt": student_prompt, "studentSees": "student persona and visible dialogue only",
    "productionWrites": False, "databaseUsed": False, "businessCodeChanged": False,
    "teachingCodeSha256": hashlib.sha256((ROOT / "student_agent/backend/teaching/typed_teaching.py").read_bytes()).hexdigest(),
    "points": points, "trace": [], "turns": [], "status": "running"}
session = {"id": "local-unclear-offtopic-" + args.case, "phase": "video", "lessonId": source["lessonId"],
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
