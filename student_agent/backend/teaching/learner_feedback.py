"""Backend-only learner reports; these are claims, never grading evidence."""
from datetime import datetime, timezone
import re
from uuid import uuid4

from backend.teaching import typed_state


def record(dialogue, *, after_class=False):
    text = dialogue.get("student_text", "").strip()
    categories = []
    if re.search(r"太简单|过于简单|没有难度|没难度|too easy", text, re.I):
        categories.append("too_easy")
    if re.search(r"(?:题目|这题|题干|选项|答案|解析|讲解|评分|判分).{0,12}(?:有误|有错|错误|不对|错了|有问题)|(?:出错题|错题目)|^有错误[。！!？?]*$|(?:question|answer|explanation).{0,16}(?:wrong|incorrect)", text, re.I):
        categories.append("reported_error")
    if not categories:
        return
    point = typed_state.current(dialogue, after_class=after_class)
    groups = [g for g in dialogue.get("question_groups", [])
              if point and g["point_id"] == point["id"]]
    dialogue.setdefault("learner_reports", []).append({
        "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories, "text": text, "status": "unreviewed",
        "point_id": point["id"] if point else None,
        "group_id": groups[-1]["id"] if groups else None,
        "stage": "postclass" if after_class else dialogue.get("stage"),
    })
