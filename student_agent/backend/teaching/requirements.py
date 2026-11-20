"""Evidence for each existing requirement; the program owns point completion."""
from copy import deepcopy


def initial(point):
    # 把课内定义的学习目标转成可分别记录证据的要求，初始均为“尚未确认”。
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
    # assessment=None 表示本轮没有学习作答，仍按已有逐项记录计算状态。
    updates = assessment["updates"] if assessment else []
    by_id = {item["id"]: item for item in point["requirements"]}
    # 引用序号只在当前知识点内有效，最后一条是尚未写入历史的本轮学生输入。
    turns = [entry["studentText"] for entry in point["assessment_history"]] + [student_text]
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
        # evidence 是模型的判断理由，sources 才是可以核对来源的学生原话。
        # 这里验证原话确实存在，是否足以证明掌握仍由模型作语义判断。
        sources = update.get("sources") or []
        if not sources:
            raise ValueError("请提供学生证据的回答序号和原文")
        for source in sources:
            turn, quote = source["turn"], source["quote"]
            if not (1 <= turn <= len(turns) and quote.strip() and quote in turns[turn - 1]):
                raise ValueError("证据必须逐字出自所指的学生回答，请核对回答序号和原文")
        # 已确认要求降级时，必须有本轮的新证据，不能仅引用旧回答推翻已有判断。
        if by_id[key]["status"] == "demonstrated" and update["status"] == "needs_help":
            if not any(source["turn"] == len(turns) for source in sources):
                raise ValueError("降级必须引用本轮学生的相反证据")
        by_id[key].update(sources=deepcopy(sources), status=update["status"], evidence=update["evidence"], studentText=student_text,
                          gap=update["gap"] if update["status"] == "needs_help" else "")
    items = point["requirements"]
    # 整点掌握由全部必要要求决定，模型本轮答对一问不代表整个点已经完成。
    complete = bool(items) and all(item["status"] == "demonstrated" for item in items)
    known = [item["text"] for item in items if item["status"] == "demonstrated"]
    # 区分已发现的具体困难与尚未获得证据的内容，后者不能直接解释为学生不会。
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
