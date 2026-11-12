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

OUT = ROOT / "student_agent/docs/knowledge-teaching/validation/2026-11-10-requirement-progress"
OUT.mkdir(parents=True, exist_ok=True)
assert not (OUT / "compound-item-probe.json").exists(), "Do not overwrite captured probe"

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


from langchain_core.callbacks import BaseCallbackHandler
saved = json.loads((OUT / "run.json").read_text(encoding="utf-8"))
turn = saved["turns"][5]
session = deepcopy(saved["session"])
session.update(dialogue=deepcopy(turn["stateBefore"]), messages=deepcopy(saved["session"]["messages"][:11]), phase="discussion")
trace = []
class Capture(BaseCallbackHandler):
    def on_chat_model_start(self, serialized, messages, **kwargs):
        trace.append({"messages": [m.model_dump(include={"type", "content", "tool_calls", "tool_call_id"}) for m in messages[0]]})
    def on_llm_end(self, response, **kwargs):
        message=response.generations[0][0].message
        trace[-1].update(content=message.content, toolCalls=message.tool_calls, usage=message.usage_metadata)
client=model.teaching_model()
client.callbacks=[Capture()]
model.teaching_model=lambda:client
changes=service.classroom_turn(session, turn["student"])
point=changes["dialogue"]["points"][1]
item=next(x for x in point["requirements"] if x["id"]=="understandingPoints:2")
evidence={"scenario":"same captured chain-queue answer after compound requirement clarification", "student":turn["student"],
    "stateBefore":turn["stateBefore"], "stateAfter":changes["dialogue"], "trace":trace,
    "reply":changes["messages"][-1]["text"], "item":item,
    "teachingCodeSha256":hashlib.sha256((ROOT/"student_agent/backend/teaching/typed_teaching.py").read_bytes()).hexdigest()}
(OUT/"compound-item-probe.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"status":item["status"],"gap":item["gap"],"reply":evidence["reply"]},ensure_ascii=False))
assert item["status"]!="demonstrated", "Compound item still falsely confirmed; retain failure"
