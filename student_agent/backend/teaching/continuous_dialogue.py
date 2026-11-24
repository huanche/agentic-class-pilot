"""One tutor proposes evidence and writes the learner-facing dialogue."""
from collections import defaultdict
from copy import deepcopy
import json
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.contracts import SessionError
from backend.infrastructure import model
from backend.teaching import card_teaching, question_cards, requirements, typed_state


PROMPT = """你负责同一名学生从上课到课后续学的对话。根据学生已经表现出的理解判断哪些掌握要求有了证据，自主决定这一轮怎样教。程序负责保存证据、判题、切换知识点和恢复进度。

<教学现场>
先读 event、focus 和 history，弄清楚学生此刻面对什么对象、刚刚说了什么、还有什么需要解释。history 是已发生的对话片段。focus.details 和 points 是备课资料，其中出现的例子、术语、符号可能是学生第一次见。只有在 history 有依据时才说“刚才你提到……”。
让学生能仅凭已展示的内容理解你的话。需要新场景时，交代对象、它们之间的关系以及眼下要解决的问题。沿用已有场景时，只补发生变化的条件。引入符号要说清它代表场景中的什么量，尤其要区分整体和局部。
根据学生的话决定解释、演示、纠错、提问或出题。学生要求直接讲时，直接讲清楚。需要提问时，可以围绕同一个任务一起检查多个相关理解点，例如让学生给出判断并指出依据。学生答了其中一部分，就接着那一部分往下教。只有当独立举例确实能帮助理解或验证目标时，才让学生自己找例子。面向学生自然说话，省去教学计划、评分术语和例行的“请用自己的话说说”。
</教学现场>

<场景示例>
以下是写法示例，实际回复使用本课内容和真实对话。
开场，目标是理解直接后继与分类关系。可以问：“图书馆有个‘图书’总类，‘文学’和‘科学’都是它的直接下级。小林把它们排成‘图书 → 文学 → 科学’，每个箭头都表示‘直接下级’。照这个画法，‘科学’成了谁的下级？哪条分类关系画错了？”
切点，假设学生刚指出文学和科学应该并列。可以接：“对，把两个类别都直接连到‘图书’下面，分类关系就清楚了。现在把这张图看成一棵树，每个类别算一个结点。用 n 表示整棵树的结点总数。如果拿掉‘文学’和‘科学’，只留下‘图书’，这时 n 是多少？这棵树算空树吗？”
课后，假设上次学生问“只剩根为什么还不算空树”。可以接：“上次你问，只剩根怎么还不算空树。把‘图书’下面的分类全部删掉，总类‘图书’还在，它自己就算一个结点。连它也删掉，才是空树。”
</场景示例>

<按事件接续>
opening 从当前知识点可观察的例子、现象或具体任务入手。chat 接住学生最新的作答或追问。如果这轮证据足以完成当前点，先答完学生的问题，简短指出他已经说明了什么。下一点由程序切换后另起 transition。
transition 从上一点已经说清的内容引出新任务，无需重答上一问。若两点没有自然联系，直接交代新场景。navigate 是学生主动切点，接续目标点已有进展；回看时发现误解就地纠正，保留已有确认。resume 从 focus.open_issue 中上次具体卡住的地方接起，结合 history 已试过的办法推进一步。没有具体卡点时，从当前点尚待学习的内容开始。
review_recent_dialogue 为 true 时，看近期作答是否有实质进展。有进展就顺着教。反复卡住时给学生换种方式继续的选择，can_skip 为 true 时也说明可用按钮跳过。课堂可提前结束并保留进度。最后一点跳过后可回看、提问或课后补学。focus 为空时，先回应当前追问，再按实际进度收束，邀请回看或续学。
</按事件接续>

<输出和证据>
只返回一个 JSON 对象。reply 必填，是直接展示给学生的中文。其余字段按需填写。
confirmations 仅用于 chat。每项格式为 {"point_id":"知识点ID","requirement_id":"要求ID","sources":[{"message":2,"quote":"学生原文"}]}。从 history 中对应编号的学生消息逐字摘录能支持该要求的原文。可跨轮累计，也可一次确认本课多个知识点的要求。教师的解释和单独一句“懂了”都不足以证明掌握。
show_card 仅在当前记忆类知识点适合用现有题卡练习时设为 true。选择题通过题卡提交，聊天中的选项不算作答证据。card 事件根据 card_result 解释已提交的选择，保护未提交题目的答案。card_confirmations 仅填本次 card_result.eligible_requirements 中你判断证据已充分的要求 ID。
open_issue 用一句话记下实际未解决的疑问或刚布置的具体任务，写明讨论对象，以便下次接着教。已解决时填空字符串。当前点最后一项达标后只保留仍未解决的学生追问，已掌握点也可留下新问题。
skip_quote 仅在 can_skip 为 true 且学生本轮明确请求跳点时逐字引用其请求。学生表示困难时让他自己决定是否跳过。
</输出和证据>"""


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reply: str = Field(min_length=1, max_length=6000)
    confirmations: list["Confirmation"] = Field(default_factory=list)
    card_confirmations: list[str] = Field(default_factory=list)
    open_issue: str | None = Field(default=None, max_length=1000)
    skip_quote: str = Field(default="", max_length=2000)
    show_card: bool = False


class Source(BaseModel):
    message: int = Field(strict=True, ge=1)
    quote: str = Field(min_length=1, max_length=2000)


class Confirmation(BaseModel):
    point_id: str
    requirement_id: str
    sources: list[Source] = Field(min_length=1, max_length=8)


def _request(dialogue, messages, focus, event, *, card_result=None, previous=None, can_skip=False):
    point_id = focus["id"] if focus else None
    recent = set(range(max(0, len(messages) - 24), len(messages)))
    on_topic = [i for i, message in enumerate(messages) if message.get("pointId") == point_id]
    issue_sequence = ((focus or {}).get("open_issue") or {}).get("sequence")
    if issue_sequence:
        recent.update(range(max(0, issue_sequence - 2), min(issue_sequence, len(messages))))
    dialogue_slice = {i + 1: messages[i] for i in sorted(recent.union(on_topic[-16:]))}
    context = {
        "event": event, "previous_point": previous, "can_skip": can_skip,
        "focus": ({key: focus.get(key) for key in ("id", "title", "type", "details", "open_issue")}
                  if focus else None),
        "since_progress": focus.get("since_progress", 0) if focus else 0,
        "review_recent_dialogue": bool(focus and focus.get("since_progress", 0) >= 3),
        "points": [{"id": point["id"], "title": point["title"], "requirements": [
            {key: item[key] for key in ("id", "text", "status")} for item in point["requirements"]]}
            for point in dialogue["points"]],
        "history": [{"message": number, **{key: message.get(key) for key in ("role", "text", "pointId", "phase")}}
                    for number, message in dialogue_slice.items()],
        "cards": [question_cards.public_group(group) for group in dialogue.get("question_groups", [])
                  if group["point_id"] == point_id][-2:],
        "card_result": card_result,
    }
    for _ in range(2):
        raw = model.complete_bounded(PROMPT, json.dumps(context, ensure_ascii=False), 35)
        try:
            proposal = Proposal.model_validate(model.json_object(raw))
            if not proposal.reply.strip():
                raise ValueError("回复不能为空")
            updates = _read_evidence(dialogue, proposal, dialogue_slice, event)
            chosen = set(proposal.card_confirmations)
            eligible = (card_result or {}).get("eligible_requirements", {})
            if len(chosen) != len(proposal.card_confirmations) or not chosen <= eligible.keys():
                raise ValueError("题卡确认必须引用本次有正确题卡结果支持的要求")
            if proposal.skip_quote and (event != "chat" or not can_skip
                    or not proposal.skip_quote.strip() or proposal.skip_quote not in messages[-1]["text"]):
                raise ValueError("跳点需要本轮明确请求，且当前知识点支持跳过")
            return proposal, updates
        except ValueError as error:
            context["repair"] = "请重新提交完整回复。校验失败：" + str(error)[:1000]
    raise ValueError("教学回复格式或证据校验失败")


def _read_evidence(dialogue, proposal, messages, event):
    eligible = {(point["id"], item["id"]) for point in dialogue["points"] for item in point["requirements"]}
    updates = defaultdict(list)
    seen = set()
    for confirmation in proposal.confirmations:
        pair = (confirmation.point_id, confirmation.requirement_id)
        if event != "chat" or pair not in eligible or pair in seen:
            raise ValueError("掌握确认必须对应本课有效要求，每项最多提交一次")
        seen.add(pair)
        refs, student_work = [], []
        for source in confirmation.sources:
            message = messages.get(source.message, {})
            if (message.get("role") != "student" or not source.quote.strip()
                    or source.quote not in message["text"] or not message.get("messageId")):
                raise ValueError("证据必须逐字引用已有学生消息")
            refs.append({"messageId": message["messageId"], "quote": source.quote})
            student_work.append(message["text"])
        updates[pair[0]].append({"requirement_id": pair[1], "status": "demonstrated",
            "evidence": "\n".join(ref["quote"] for ref in refs), "gap": "", "evidenceRefs": refs,
            "sourceText": "\n".join(dict.fromkeys(student_work))})
    return updates


def _update_point(point, updates, *, after_class, student_text="", message_id=None, attempted=False):
    already = {item["id"] for item in point["requirements"] if item["status"] == "demonstrated"}
    updates = [update for update in updates if update["requirement_id"] not in already]
    if not updates and not attempted:
        return
    stage = "postclass" if after_class else "recall"
    evidence = "\n".join(dict.fromkeys(update["evidence"] for update in updates))
    outcome = requirements.apply(point, {"updates": updates, "evidence": evidence,
        "answer_result": "misconception" if any(u["status"] == "needs_help" for u in updates) else "unclear",
        "next_step": (point.get("open_issue") or {}).get("text", "")}, student_text)
    for item in point["requirements"]:
        update = next((u for u in updates if u["requirement_id"] == item["id"]), None)
        if update:
            item["evidenceRefs"] = update["evidenceRefs"]
            item["studentText"] = update.get("sourceText", student_text)
    mastered = outcome["result"] == "mastered"
    point.update(status=outcome["result"], evidence=evidence or point["evidence"],
                 known_parts=outcome["known_parts"], gaps=outcome["gaps"], next_step=outcome["next_step"])
    if mastered:
        point.update(recall_done=True, reinforce_done=True, reinforcement_required=False,
                     mastered_in=point.get("mastered_in") or stage, open_issue=None)
    if attempted or updates:
        turn_evidence = "\n".join(dict.fromkeys(ref["quote"] for update in updates
            for ref in update["evidenceRefs"] if ref.get("messageId") == message_id and "quote" in ref))
        point["assessment_history"].append({"stage": stage,
            "result": outcome["result"] if turn_evidence or message_id is None else "unknown",
            "studentText": student_text, "evidence": turn_evidence if message_id else evidence})
    if any(update["status"] == "demonstrated" for update in updates):
        point["since_progress"] = 0
    elif attempted:
        point["since_progress"] = point.get("since_progress", 0) + 1


def _set_focus(dialogue, point, *, after_class):
    dialogue["focus_id"] = point["id"] if point else None
    dialogue["review_point_id"] = point["id"] if point and point["status"] == "mastered" else None
    if not after_class:
        dialogue["stage"] = "recall" if point else "wrapup"
        if point is None and all(p["status"] == "mastered" for p in dialogue["points"]):
            dialogue["completion_reason"] = "all_mastered"
    dialogue["current_task"] = typed_state.task(dialogue, after_class=after_class)


def _can_skip(dialogue, *, after_class):
    return bool(typed_state.next_point(dialogue, after_class=after_class)
                or typed_state.can_skip_last(dialogue, after_class=after_class))


def _next_pending(dialogue, focus, *, after_class):
    points = dialogue["points"]
    index = points.index(focus)
    ordered = points if after_class else points[index + 1:] + points[:index]
    return next((p for p in ordered if p["status"] != "mastered" and (after_class or not p.get("skipped"))), None)


def _resume_point(dialogue):
    def priority(point):
        issue = point.get("open_issue") or {}
        return bool(issue.get("encountered")), issue.get("sequence", 0)

    pending = [point for point in dialogue["points"] if point["status"] != "mastered" or point.get("open_issue")]
    return max(pending, key=priority, default=None)


def _remember_issue(focus, proposal, sequence, event):
    if not focus or proposal.open_issue is None:
        return
    text = proposal.open_issue.strip()
    old = focus.get("open_issue") or {}
    encountered = event in {"chat", "card"} or old.get("encountered", False)
    focus["open_issue"] = {"text": text, "sequence": sequence, "encountered": encountered} if text else None


def _assistant(dialogue, focus, proposal, *, after_class, keep_focus=True):
    message = {"role": "assistant", "text": proposal.reply.strip(), "pointId": focus["id"] if focus else None,
               "phase": _phase(dialogue, after_class, focus)}
    if keep_focus and proposal.show_card and focus and focus["type"] == "memory":
        pending = card_teaching.pending_card(dialogue, focus)
        if (not pending and focus["status"] != "mastered" and dialogue.get("cards_version") == 1):
            # Keep the Agent's reply while reusing the existing card lifecycle.
            card_teaching.ensure_card(dialogue, after_class, complete=lambda prompt, payload:
                                      model.complete_bounded(prompt, payload, 35))
            pending = card_teaching.pending_card(dialogue, focus)
        if pending:
            message["cardId"] = pending["id"]
    dialogue["reply"] = message["text"]
    return message


def _phase(dialogue, after_class, focus):
    return ("postclass-remediation" if focus else "postclass-open") if after_class else dialogue["stage"]


def run(session, event, *, text=None, direction=None, group_id=None, answers=None):
    """Return one atomic candidate for a classroom or postclass interaction."""
    after_class = session["phase"] == "done"
    dialogue = deepcopy(session["dialogue"])
    messages = list(session["messages"])
    focus = typed_state.current(dialogue, after_class=after_class)
    previous = None
    if event == "resume":
        focus = _resume_point(dialogue)
        dialogue["resuming_review_issue"] = bool(focus and focus["status"] == "mastered")
    elif event == "navigate":
        dialogue["resuming_review_issue"] = False
        target = (typed_state.next_point if direction == "next" else typed_state.previous_point)
        destination = target(dialogue, after_class=after_class)
        if not destination and not (direction == "next" and _can_skip(dialogue, after_class=after_class)):
            raise SessionError(409, "没有可切换的知识点", code="INVALID_ACTION")
        if direction == "next" and focus and focus["status"] != "mastered":
            focus["skipped"] = True
        previous, focus = focus, destination
    _set_focus(dialogue, focus, after_class=after_class)
    was_mastered = bool(focus and focus["status"] == "mastered")
    lesson_was_mastered = all(point["status"] == "mastered" for point in dialogue["points"])
    card_result = None
    if event == "chat":
        messages.append({"role": "student", "text": text.strip(), "messageId": session.get("_studentMessageId") or uuid4().hex,
                         "pointId": focus["id"] if focus else None, "phase": _phase(dialogue, after_class, focus)})
    elif event == "card":
        group, card_updates, answer_text, _ = card_teaching.grade_submission(dialogue, focus, group_id, answers)
        card_result = {"cardId": group_id, "submitted": {key: group["results"][key] for key in answers},
                       "eligible_requirements": {update["requirement_id"]: update["evidenceRefs"]
                                                 for update in card_updates if update["status"] == "demonstrated"}}
    proposal, updates = _request(dialogue, messages, focus, event, card_result=card_result,
        previous=previous["id"] if previous else None,
        can_skip=_can_skip(dialogue, after_class=after_class))
    if event == "chat":
        for point in dialogue["points"]:
            _update_point(point, updates.get(point["id"], []), after_class=after_class,
                          student_text=text.strip(), message_id=messages[-1]["messageId"],
                          attempted=point is focus and not was_mastered)
    elif event == "card":
        accepted = [update for update in card_updates
                    if update["status"] != "demonstrated" or update["requirement_id"] in proposal.card_confirmations]
        _update_point(focus, accepted, after_class=after_class, student_text=answer_text, attempted=True)
    _remember_issue(focus, proposal, len(messages) + 1, event)
    resolved_review = dialogue.get("resuming_review_issue") and focus and not focus.get("open_issue")
    advance = bool(focus and focus["status"] == "mastered" and (not was_mastered or resolved_review))
    messages.append(_assistant(dialogue, focus, proposal, after_class=after_class,
                               keep_focus=not (advance or proposal.skip_quote)))
    newly_complete_in_open_chat = (focus is None and not lesson_was_mastered
                                   and all(point["status"] == "mastered" for point in dialogue["points"]))
    if proposal.skip_quote or advance or newly_complete_in_open_chat:
        if proposal.skip_quote and not advance:
            focus["skipped"] = focus["status"] != "mastered"
            target = typed_state.next_point(dialogue, after_class=after_class)
        else:
            target = _next_pending(dialogue, focus, after_class=after_class) if focus else None
        dialogue["resuming_review_issue"] = False
        _set_focus(dialogue, target, after_class=after_class)
        continuation, _ = _request(dialogue, messages, target, "transition", previous=focus["id"] if focus else None)
        _remember_issue(target, continuation, len(messages) + 1, "transition")
        messages.append(_assistant(dialogue, target, continuation, after_class=after_class))
    changed = {"dialogue": dialogue, "messages": messages}
    if after_class:
        changed.update(postclassStage="remediation" if typed_state.current(dialogue, after_class=True) else "open",
                       feedback=typed_state.feedback(dict(session, dialogue=dialogue)))
    else:
        changed["phase"] = "discussion"
    return changed
