"""Read archived inputs, call the configured real model, export reviewable results. No DB writes."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "student_agent"))
from backend.content import knowledge, lesson_content
from backend.content.context import classroom_materials
from backend.content.prompts import KNOWLEDGE_EXTRACTION_PROMPT
from backend.content.knowledge_schema import submit_knowledge_points
from backend.teaching import service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for rel in ("student_agent/.env.local", "platform/.env"):
        config = dotenv_values(ROOT / rel, encoding="utf-8-sig", interpolate=False)
        for key, alias in (("STUDENT_AGENT_API_KEY", "AGENT_LLM_API_KEY"),
                           ("STUDENT_AGENT_BASE_URL", "AGENT_LLM_BASE_URL"),
                           ("STUDENT_AGENT_MODEL", "AGENT_LLM_MODEL")):
            value = config.get(key) or config.get(alias)
            if value:
                os.environ.setdefault(key, value)
    os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"
    archive = ROOT / "student_agent/evidence/arrays-e2e-2026-11-11"
    source = json.loads((archive / "classroom.json").read_text(encoding="utf-8-sig"))["classroom"]
    outline = json.loads((archive / "outline-result.json").read_text(encoding="utf-8-sig"))
    def course_title(value):
        if isinstance(value, dict):
            if value.get("courseTitle"):
                return value["courseTitle"]
            for item in value.values():
                found = course_title(item)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = course_title(item)
                if found:
                    return found
    name = course_title(outline)
    assert name, "Archived program course title is required"
    materials = classroom_materials(source["scenes"])
    def save(filename, value):
        (args.output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    save("input.json", {"course_name": name, "materials": materials})
    save("tool-schema.json", submit_knowledge_points.model_json_schema())
    (args.output / "prompt.txt").write_text(KNOWLEDGE_EXTRACTION_PROMPT, encoding="utf-8")
    result = knowledge.learning_points(materials, "local-review", "arrays", course_name=name)
    clean = {"points": [{k: point[k] for k in ("name", "explanation")} for point in result.points]}
    save("knowledge-points.json", clean)
    save("extraction-report.json", asdict(result))
    body = lesson_content.build("local-review", "arrays", "archived-2026-11-11", "core-v3",
                                result.points, materials, scenes=source["scenes"])
    lesson_content.validate(body)
    save("lesson-content.json", body)
    session = {"id": "local-core-review", "phase": "video", "lessonId": "arrays",
               "videoRevision": "archived-2026-11-11", "context": {"courseId": "local-review"},
               "dialogue": service.new_dialogue(result.points), "messages": [], "lessonContent": body}
    session = lesson_content.bind(session)
    session.update(service.start_discussion(session))
    transcript = {"opening": session["messages"][-1]["text"], "turns": []}
    # These are explicit test inputs, not real student evidence.
    for answer in ("我不太确定数组的下标从哪里开始。", "数组下标从0开始，int a[5]的合法下标是0到4，a[5]越界。"):
        session.update(service.classroom_turn(session, answer))
        transcript["turns"].append({"simulatedStudent": answer, "assistant": session["messages"][-1]["text"],
                                    "stage": session["dialogue"]["stage"],
                                    "evaluation": session["dialogue"]["evaluation"]})
        save("teaching-smoke.json", transcript)
    session.update(service.finish(session))
    save("feedback.json", session["feedback"])
    text = "# 核心知识点提取结果\n\n课程：" + name + "\n\n"
    for index, point in enumerate(clean["points"], 1):
        text += f"## {index}. {point['name']}\n\n{point['explanation']}\n\n"
    (args.output / "知识点结果.md").write_text(text, encoding="utf-8")
    print(json.dumps({"course": name, "pointCount": len(result.points), "modelCalls": result.model_calls,
                      "teachingTurns": len(transcript["turns"]), "productionWrites": False}, ensure_ascii=True))


if __name__ == "__main__":
    main()
