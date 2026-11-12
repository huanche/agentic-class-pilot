"""Evidence for each existing requirement; the program owns point completion."""
from copy import deepcopy


def initial(point):
    details = point["details"]
    fields = {"memory": ["requiredElements"], "concept": ["understandingPoints"],
              "design": ["capability", "constraints", "successCriteria"]}[point["type"]]
    result = []
    for field in fields:
        texts = [details[field]] if field == "capability" else details[field]
        for index, text in enumerate(texts, 1):
            result.append({"id": f"{field}:{index}", "text": text, "status": "unconfirmed",
                           "evidence": "", "studentText": "", "gap": ""})
    return result


def apply(point, assessment, student_text):
    """Apply scoped observations, then derive the entire point's verdict."""
    updates = assessment["updates"] if assessment else []
    by_id = {item["id"]: item for item in point["requirements"]}
    seen = set()
    for update in updates:
        key = update["requirement_id"]
        if key not in by_id or key in seen:
            raise ValueError("评估要求必须属于当前知识点，且不能重复")
        seen.add(key)
        if update["status"] not in {"demonstrated", "needs_help"} or not update["evidence"].strip():
            raise ValueError("要求更新必须包含状态和学生表现依据")
        if update["status"] == "needs_help" and not update["gap"].strip():
            raise ValueError("需要帮助的要求必须说明具体缺口")
        by_id[key].update(status=update["status"], evidence=update["evidence"], studentText=student_text,
                          gap=update["gap"] if update["status"] == "needs_help" else "")
    items = point["requirements"]
    complete = bool(items) and all(item["status"] == "demonstrated" for item in items)
    known = [item["text"] for item in items if item["status"] == "demonstrated"]
    gaps = [item["gap"] if item["status"] == "needs_help" else "尚未确认：" + item["text"]
            for item in items if item["status"] != "demonstrated"]
    answer_result = assessment["answer_result"] if assessment else "unclear"
    outcome = ("mastered" if complete else "misconception" if answer_result == "misconception" else
               "partial" if known or any(item["status"] == "needs_help" for item in items) else
               "unanswered" if answer_result == "unanswered" else "unclear")
    return {"result": outcome, "evidence": assessment["evidence"] if assessment else "",
            "known_parts": known, "gaps": gaps, "next_step": assessment["next_step"] if assessment else point["next_step"]}


def public(point):
    return deepcopy(point["requirements"])
