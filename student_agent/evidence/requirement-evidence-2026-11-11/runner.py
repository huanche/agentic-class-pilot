"""Replay archived real-course inputs against the current teaching service, no DB."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.infrastructure import model
from backend.teaching import service, typed_teaching

for base in [ROOT, Path("E:/LMS系统参考/项目/agentic-class-pilot-running")]:
    for name in ["student_agent/.env.local", "platform/.env"]:
        path = base / name
        if path.exists():
            config = dotenv_values(path, interpolate=False, encoding="utf-8-sig")
            for target, fallback in [("STUDENT_AGENT_API_KEY", "AGENT_LLM_API_KEY"),
                                     ("STUDENT_AGENT_BASE_URL", "AGENT_LLM_BASE_URL"),
                                     ("STUDENT_AGENT_MODEL", "AGENT_LLM_MODEL")]:
                value = config.get(target) or config.get(fallback)
                if value:
                    os.environ.setdefault(target, value)
os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"
archive = ROOT / "student_agent/evidence/new-knowledge-audit-2026-11-10"
boundary = json.loads((archive / "boundary/run.json").read_text(encoding="utf-8"))
procedural = json.loads((archive / "procedural/run.json").read_text(encoding="utf-8"))
cases = []
for name in ["noise", "understood", "question", "unknown", "wrong", "partial"]:
    case = next(c for c in boundary["cases"] if c["name"] == name)
    cases.append((name, case["before"], case["student"], "unchanged" if name in
                  {"noise", "understood", "question", "partial"} else "needs_help"))
cases.append(("attempt-incomplete", cases[0][1],
              "rear=8已经到了数组末端，再写入会越界。但我还解释不清为什么前面会有空位。", "needs_help"))
original = next(c for c in procedural["cases"] if c["case"] == "illegal-empty-pop")
state = service.new_dialogue([original["point"]])
point = state["points"][0]
question = original["opening"]
point.update(task_question=question, latest_question=question, question_targets=["capability:1"])
record = {"stage": "recall", "text": question, "target_ids": ["capability:1"], "planned_action": "ask"}
point["question_history"].append(record)
point["help_history"].append(record)
cases.append(("illegal-empty-pop", state, original["turns"][0]["student"], "unasked_unchanged"))
known = next(c for c in boundary["cases"] if c["name"] == "correct_full")["after"]
cases.append(("known-not-mentioned", known, "为什么队尾到数组最后一个位置不能直接加1呢？", "unchanged"))
cases.append(("known-contradicted", known, "我觉得循环队列空时front不等于rear，满时才是front等于rear。", "contradiction"))
memory = json.loads((archive / "conceptual/run.json").read_text(encoding="utf-8"))["cases"][0]
cases.append(("correct-equivalent", memory["turns"][0]["before"], memory["turns"][0]["answer"], "mastered"))

selected = os.environ.get("AUDIT_CASES", "").split(",")
out = Path(os.environ.get("AUDIT_OUTPUT", str(Path(__file__).with_name("run.json"))))
out.parent.mkdir(parents=True, exist_ok=True)
report = {"model": model.teaching_model().model_name, "cases": [], "seam": "typed_teaching.run, no persistence"}
for repeat in range(int(os.environ.get("AUDIT_REPEAT", "2"))):
    for name, before, answer, expected in cases:
        if selected != [""] and name not in selected:
            continue
        entry = {"name": name, "repeat": repeat + 1, "before": before, "student": answer, "expected": expected}
        state = deepcopy(before)
        state["student_text"] = answer
        try:
            after = typed_teaching.run(state)
            items = after["points"][0]["requirements"]
            if expected == "unchanged":
                passed = items == before["points"][0]["requirements"]
            elif expected == "unasked_unchanged":
                passed = next(r for r in items if r["id"] == "successCriteria:3")["status"] == "unconfirmed"
                passed = passed and any(r["status"] == "needs_help" for r in items)
            elif expected == "needs_help":
                passed = items[0]["status"] == "needs_help" and not any(r["status"] == "demonstrated" for r in items)
            elif expected == "contradiction":
                passed = next(r for r in items if r["id"] == "understandingPoints:3")["status"] == "needs_help"
            else:
                passed = after["points"][0]["status"] == "mastered"
            entry.update(after=after, passed=passed)
        except Exception as exc:
            entry.update(passed=False, errorType=type(exc).__name__)
        report["cases"].append(entry)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": name, "repeat": repeat + 1, "passed": entry["passed"],
                          "errorType": entry.get("errorType")}, ensure_ascii=False), flush=True)
sys.exit(0 if all(c["passed"] for c in report["cases"]) else 1)
