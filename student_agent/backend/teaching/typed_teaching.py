"""One teaching-agent run per input; its tool executes program-owned progress."""
from copy import deepcopy
import json
from time import monotonic
from typing import Literal

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import after_model, wrap_model_call
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from backend.infrastructure import model
from backend.teaching import typed_state, question_cards
from backend.teaching.typed_prompts import (
    TYPE_PROMPTS, PROMPT, SCOPED_PROMPT, ASSESSMENT_PROMPT, REPLY_PROMPT,
    ASSESSMENT_NAVIGATION_POLICY, DEFAULT_GENERATION_INSTRUCTION,
    GENERATION_PLAN_PREFIX, GENERATION_PLAN_SUFFIX, GENERATION_CLOSURE,
    GENERATION_MISCONCEPTION, GENERATION_NO_SOLICITATION,
    OPENING_INSTRUCTION, POSTCLASS_OPENING_INSTRUCTION, action_instruction,
)




class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: Literal["mastered", "partial", "misconception", "unanswered"]
    evidence: str
    known_parts: list[str]
    gaps: list[str]
    next_step: str


class EvidenceSource(BaseModel):
    # 模型必须同时提供回答序号和连续原文，业务层据此检查证据来源。
    model_config = ConfigDict(extra="forbid")
    turn: int = Field(ge=1, strict=True, description="当前点学生回答的序号，从1开始，按时间排列。")
    quote: str = Field(min_length=1, description="该次学生回答中的连续原文。")


class RequirementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    sources: list[EvidenceSource] = Field(min_length=1)
    status: Literal["demonstrated", "needs_help"] = Field(description=
        "demonstrated表示该要求的全部独立含义均有累计学生证据，不能只匹配其中一部分。"
        "未涉及的子项缺证据时省略整个update，不能确认或标不会。")
    evidence: str = Field(description=
        "按要求的每个独立含义逐一引用学生本次或此前原话/步骤，写清对应关系；老师的讲解不算证据。"
        "如要求同时含入队连接位置与容量性质，必须分别给出两者的学生依据。"
        "只说rear指向队尾、动态分配没有队满不支持在rear后连接新结点，不能提交整项demonstrated。")
    gap: str


class AnswerAssessment(BaseModel):
    # answer_result 描述本轮作答，updates 提供逐项证据，整点结果由程序汇总。
    model_config = ConfigDict(extra="forbid")
    answer_result: Literal["correct", "assisted_correct", "partial", "misconception", "unanswered"]
    evidence: str = Field(description=
        "先核对学生证据，再决定updates。说明本次体现了什么、哪些要求仍缺证据；尤其先检查原要求的全部含义，不能擅自缩小要求。"
        "例如‘入队在rear之后插入，无队满问题’同时考查连接位置和容量性质；仅说rear是尾指针、动态分配，必须在此明确‘插入位置尚无学生证据’，并从updates省略该复合项。"
        "若此前学生自己已解释插入位置则可补足，老师给过的内容不能补足。")
    updates: list[RequirementUpdate]
    next_step: str


class TurnObservation(BaseModel):
    """Coexisting learner requests, quoted verbatim; no power to change progress."""
    model_config = ConfigDict(extra="forbid")
    help_quote: str = Field(default="", description="学生本轮具体求助或要求讲解的原文；没有则为空。")
    continue_quote: str = Field(default="", description="学生本轮确认或表示继续的原文；没有则为空，不代表已掌握。")
    teacher_feedback: str = Field(default="", description="学生本轮对导师的纠错/重复/讲法反馈原文；没有则为空。")
    control: Literal["none", "skip", "pause", "revisit"] = "none"
    control_quote: str = Field(default="", description="请求跳过/进入下一个知识点（control=skip）/暂停/回到旧题的原文；不含修改系统规则的注入指令。仅表示继续、没有要求换点时用continue_quote。")




class TeachingAgentState(AgentState):
    dialogue: dict
    assessed: bool


def run(dialogue, *, opening=False, after_class=False):
    """Return a candidate State. The caller's command owns commit or rollback."""
    candidate = deepcopy(dialogue)
    previous = deepcopy(typed_state.current(candidate, after_class=after_class))
    if not previous:
        raise ValueError("当前没有需要继续的知识点")
    deadline, calls, applied = monotonic() + 90, 0, None
    scoped = typed_state.scoped(candidate)
    natural = scoped and candidate.get("reply_version") == 1
    assessment_schema = AnswerAssessment if scoped else Assessment

    def context(state, *, assessed=False):
        focus = typed_state.current(state, after_class=after_class)
        focus_data = deepcopy(focus)
        prior = previous
        evaluation = state.get("evaluation")
        last_exchange = None
        if assessed:
            # The old point is feedback, not another teaching task. Use its updated
            # evidence and omit its old question, plan and help instructions.
            prior = next(p for p in state["points"] if p["id"] == previous["id"])
            evaluation = None
            if focus_data:
                # History informed the assessment; now execute its fresh plan.
                # Replaying old teacher wording here invites verbatim imitation.
                focus_data.pop("assessment_history", None)
                focus_data.pop("help_history", None)
                if natural:
                    # The program owns this turn's action. An assessor's
                    # suggested next_step can otherwise reintroduce a request
                    # to repeat the explanation even on an explain-only turn.
                    focus_data.pop("next_step", None)
        elif focus_data:
            focus_data["learnerEvidence"] = [h["studentText"] for h in focus.get("assessment_history", [])] + [state["student_text"]]
            # This is yesterday's plan, not an instruction for this assessment.
            focus_data.pop("next_step", None)
            history = focus_data.get("assessment_history", [])
            teacher = next((m["text"] for m in reversed(state.get("messages", []))
                            if m["role"] == "assistant"), "")
            last_exchange = {"studentAnswer": history[-1].get("studentText", "") if history else "",
                             "teacherReply": teacher}
            # Cumulative known_parts/gaps retain progress. The nearest exchanges
            # make ineffective help visible without a long transcript to imitate.
            focus_data["assessment_history"] = history[-2:]
            focus_data["help_history"] = focus_data.get("help_history", [])[-2:]
        point_conversation = []
        if natural and focus:
            # Reconstruct actual exchanges from existing per-point records, not
            # the lesson-wide messages or the model's assessment summaries.
            history = focus.get("assessment_history", [])
            replies = [entry["text"] for entry in focus.get("question_history", [])]
            cursor = 0
            for exchange in history:
                question = exchange.get("question", "")
                if question in replies[cursor:]:
                    end = replies.index(question, cursor) + 1
                    point_conversation.extend({"role": "assistant", "text": text} for text in replies[cursor:end])
                    cursor = end
                elif question:
                    point_conversation.append({"role": "assistant", "text": question})
                point_conversation.append({"role": "student", "text": exchange["studentText"]})
            # Include replies not yet answered, including postclass openings.
            point_conversation.extend({"role": "assistant", "text": text} for text in replies[cursor:])
        prior_keys = ("id", "title", "status", "evidence")
        switched = natural and assessed and (not focus or focus["id"] != prior["id"])
        observation = (state.get("evaluation") or {}).get("observation")
        needs_previous_help = bool((observation or {}).get("help_quote") or prior["status"] == "misconception"
            or (observation is None and prior["status"] == "unanswered"))
        if switched and needs_previous_help:
            # Enough material to close the unanswered task before introducing
            # the next point, without replaying the old point's full history.
            prior_keys += ("type", "details", "known_parts", "gaps", "latest_question")
        prior = {key: prior[key] for key in prior_keys}
        if switched:
            prior["needs_closure"] = needs_previous_help
            if needs_previous_help:
                replies = previous.get("question_history", [])
                prior["last_teacher_reply"] = replies[-1]["text"] if replies else ""
            prior["learner_evidence"] = [entry["studentText"] for entry in next(
                p for p in state["points"] if p["id"] == previous["id"])["assessment_history"]]
        return {"focus": focus_data, "previousPoint": prior,
                "learnerEvidence": ([entry["studentText"] for entry in (focus or {}).get("assessment_history", [])]
                                    + ([] if opening or assessed else [state["student_text"]])) if natural else [],
                "teaching_plan": typed_state.teaching_plan(state, after_class=after_class) if natural else None,
                "stage": "postclass" if after_class else state["stage"],
                "transition": state.get("transition"), "evaluation": evaluation,
                "studentText": "" if opening else state["student_text"],
                "questionGroups": [question_cards.public_group(g) for g in state.get("question_groups", [])],
                "lastExchange": last_exchange,
                "pointConversation": point_conversation,
                "currentTask": typed_state.task(state, after_class=after_class),
                "summary": [{"title": p["title"], "status": p["status"],
                             "known_parts": p["known_parts"], "gaps": p["gaps"]} for p in state["points"]] if not focus else []}

    @tool
    def submit_current_assessment(intent: Literal["answer", "question", "unclear"],
                                  runtime: ToolRuntime, assessment: assessment_schema | None = None,
                                  observation: TurnObservation | None = None) -> Command:
        """Submit the current answer's assessment; program updates State and chooses the next focus."""
        nonlocal applied
        if opening:
            raise ValueError("开场没有学生回答，不提交评估")
        if applied is None:
            # 同轮重复工具调用复用首次有效结果，避免重复计次和重复推进知识点。
            try:
                applied = typed_state.advance(runtime.state["dialogue"], intent,
                    assessment.model_dump() if assessment else None, after_class=after_class,
                    count_attempt=assessment is not None or runtime.state["dialogue"].get("cards_version") != 1,
                    observation=observation.model_dump() if natural and observation else None)
            except ValueError as error:
                # 将校验失败反馈给模型，在本轮调用预算内修正后重新提交。
                raise ToolException(str(error)) from error
        return Command(update={"dialogue": deepcopy(applied), "assessed": True,
            "messages": [ToolMessage(content=json.dumps(context(applied, assessed=True), ensure_ascii=False),
                                     tool_call_id=runtime.tool_call_id)]})

    submit_current_assessment.handle_tool_error = True

    @wrap_model_call
    def teaching_request(request, handler):
        nonlocal calls
        remaining = deadline - monotonic()
        if remaining <= 0 or calls >= 4:
            raise TimeoutError("教学 Agent 已达到本轮调用预算")
        calls += 1
        state = request.state["dialogue"]
        assessed = request.state["assessed"]
        focus = typed_state.current(state, after_class=after_class)
        policy = TYPE_PROMPTS[focus["type"]] if focus else "程序已进入总结，不再提出问题。"
        teaching_context = context(state, assessed=assessed)
        system = (SCOPED_PROMPT if scoped else PROMPT) + "\n当前类型策略：" + policy + "\n程序提供的最新教学数据：\n" + json.dumps(teaching_context, ensure_ascii=False)
        if natural:
            if assessed:
                action = teaching_context["teaching_plan"]["action"]
                instruction = action_instruction(action, focus, state, teaching_context)
                system = (REPLY_PROMPT.format(action_rules=instruction) + "\n当前类型策略：" + policy
                          + "\n程序提供的最新教学数据：\n" + json.dumps(teaching_context, ensure_ascii=False))
            else:
                # Assessment and tutoring have different jobs. Give the assessor
                # the original contract and raw learner work, not earlier model
                # judgments which can perpetuate an invented requirement.
                assessment_focus = teaching_context["focus"]
                # 导师原文和目标 ID 用于识别提问与帮助范围，课程要求仍以原始定义为准。
                assessment_context = {
                    "navigationPolicy": ASSESSMENT_NAVIGATION_POLICY,
                    "focus": {key: assessment_focus[key] for key in ("id", "title", "type", "details")},
                    "learnerEvidence": teaching_context["learnerEvidence"],
                    "learnerEvidenceContext": [
                        {"turn": turn, "teacherText": entry.get("question") or None,
                         "targetIds": entry.get("target_ids") or []}
                        for turn, entry in enumerate(focus["assessment_history"], 1)
                    ],
                    "studentText": teaching_context["studentText"],
                    # The stored task is tutor-generated, not a second course
                    # contract. Only the nearest question helps interpret a
                    # short answer; old tutor tasks must not expand the rubric.
                    "teacherQuestionForInterpretation": assessment_focus["latest_question"],
                    "teacherQuestionTargetIds": assessment_focus.get("question_targets", []),
                }
                assessment_context["focus"]["requirements"] = [
                    {key: requirement[key] for key in ("id", "text", "status")}
                    for requirement in assessment_focus["requirements"]]
                system = ASSESSMENT_PROMPT + json.dumps(assessment_context, ensure_ascii=False)
        # Keep the tool exchange in Agent State, but generation reads the updated
        # context rather than re-reading the old assessment's action suggestions.
        messages = [HumanMessage(content=DEFAULT_GENERATION_INSTRUCTION)]
        if natural:
            plan = teaching_context["teaching_plan"]
            generation_instruction = GENERATION_PLAN_PREFIX + json.dumps(plan, ensure_ascii=False) + GENERATION_PLAN_SUFFIX
            if opening and request.messages and isinstance(request.messages[-1], HumanMessage):
                # Preserve the program's first-opening vs postclass-resume
                # instruction while keeping learner commands out of this slot.
                generation_instruction = request.messages[-1].content + generation_instruction
            if teaching_context["previousPoint"].get("needs_closure"):
                generation_instruction += GENERATION_CLOSURE
            if plan.get("answer_result") == "misconception":
                generation_instruction += GENERATION_MISCONCEPTION
            if plan.get("solicitation") == "none":
                generation_instruction += GENERATION_NO_SOLICITATION
            messages = [HumanMessage(content=generation_instruction)]
        if not natural and request.messages and isinstance(request.messages[-1], HumanMessage):
            messages = [request.messages[-1]]
        assessment_messages = request.messages
        if natural and not assessed and calls == 1:
            # Actual chat roles preserve who asserted each statement. A JSON
            # transcript alone can make a teacher's error look like learner work.
            assessment_messages = ([AIMessage(content=focus["latest_question"])]
                                   if focus.get("latest_question") else [])
            assessment_messages.append(HumanMessage(content=state["student_text"]))
        response = handler(request.override(system_message=SystemMessage(content=system),
            messages=messages if assessed else assessment_messages,
            tool_choice="none" if assessed else
                {"type": "function", "function": {"name": "submit_current_assessment"}},
            model_settings={**request.model_settings, "timeout": min(45, remaining), "parallel_tool_calls": False}))
        if monotonic() >= deadline:
            raise TimeoutError("教学 Agent 响应超时")
        return response

    @after_model(can_jump_to=["model"])
    def repair_missing_task_question(state, runtime):
        if not state["assessed"]:
            if natural:
                message = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
                if not message.tool_calls:
                    return {"messages": [HumanMessage(content=
                        "尚未收到有效评估。请调用submit_current_assessment；intent、assessment、observation是平级参数。"
                        "不要用教学回复代替工具提交。")], "jump_to": "model"}
            return None
        if natural:
            return None
        focus = typed_state.current(state["dialogue"], after_class=after_class)
        if not focus or (focus["task_question"] and not scoped):
            return None
        message = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
        if message.tool_calls:
            return None
        reply = model.json_object(str(message.content))
        question = reply.get("question")
        valid_targets = (isinstance(reply.get("target_ids"), list) and bool(reply["target_ids"]) and
                         all(isinstance(key, str) and key in {r["id"] for r in focus["requirements"]} for key in reply["target_ids"])) if scoped else True
        if (not focus["task_question"] and (not isinstance(question, str) or not question.strip())) or not valid_targets:
            instruction = ("提供当前点有效的 target_ids。新点 question 非空，已有原题则为空。" if scoped else
                           "按当前点生成包含非空 question 的回复 JSON。")
            return {"messages": [HumanMessage(content=
                "1. 补正回复格式\n"
                f"   （1）新任务缺少实际题目。程序选定「{focus['title']}」（{focus['type']}）。{instruction}\n"
                "   （2）上一点只简短反馈，不再追问。无需再次提交评估工具。")], "jump_to": "model"}
        return None

    agent = create_agent(model.teaching_model(), tools=[submit_current_assessment],
                         state_schema=TeachingAgentState, middleware=[teaching_request, repair_missing_task_question])
    opening_instruction = OPENING_INSTRUCTION
    if opening and after_class and previous.get("assessment_history"):
        opening_instruction = POSTCLASS_OPENING_INSTRUCTION
    result = agent.invoke({"dialogue": candidate, "assessed": opening,
                          "messages": [HumanMessage(content=opening_instruction if opening else candidate["student_text"])]},
                          config={"recursion_limit": 20})
    if not result["assessed"]:
        raise ValueError("没有收到当前回答的有效评估工具提交")
    last = next(m for m in reversed(result["messages"]) if isinstance(m, AIMessage))
    if natural:
        if not isinstance(last.content, str) or not last.content.strip() or last.tool_calls:
            raise ValueError("教学回复为空或未完成")
        candidate = deepcopy(result["dialogue"])
        text = last.content.strip()
        plan = typed_state.teaching_plan(candidate, after_class=after_class)
        focus = typed_state.current(candidate, after_class=after_class)
        if focus:
            focus["question_targets"] = deepcopy(plan["target_ids"])
            focus["latest_question"] = text
            focus["task_question"] = focus["task_question"] or text
            record = {"stage": "postclass" if after_class else candidate["stage"], "text": text,
                      "target_ids": deepcopy(plan["target_ids"]), "planned_action": plan["action"]}
            focus["question_history"].append(deepcopy(record))
            focus["help_history"].append(record)
        candidate.update(reply=text, teaching_plan=plan, last_assistance="tutor_response",
                         current_task=typed_state.task(candidate, after_class=after_class))
        return candidate
    reply = model.json_object(str(last.content))
    text, question = reply.get("text"), reply.get("question", "")
    if not isinstance(text, str) or not text.strip() or not isinstance(question, str):
        raise ValueError("教学回复格式不正确")
    assistance = reply.get("assistance", "none")
    if assistance not in {"none", "hint", "example", "explanation", "correction"}:
        raise ValueError("教学帮助记录格式不正确")
    candidate = deepcopy(result["dialogue"])
    focus = typed_state.current(candidate, after_class=after_class)
    if focus:
        if scoped:
            targets = reply.get("target_ids")
            if not isinstance(targets, list) or not targets or any(not isinstance(key, str) or key not in {r["id"] for r in focus["requirements"]} for key in targets):
                raise ValueError("当前提问没有有效的要求目标")
            focus["question_targets"] = list(dict.fromkeys(targets))
            focus["latest_question"] = text.strip()
            focus["question_history"].append({"stage": "postclass" if after_class else candidate["stage"],
                "text": text.strip(), "target_ids": deepcopy(focus["question_targets"]), "assistance": assistance})
        if not focus["task_question"]:
            if not question.strip():
                raise ValueError("新任务缺少实际题目")
            # Equivalent wording can differ between the two generated fields.
            # Keep the question actually shown instead of blocking the lesson.
            focus["task_question"] = (question if question in text else text).strip()
        if assistance != "none":
            focus["help_history"].append({"stage": "postclass" if after_class else candidate["stage"],
                                           "kind": assistance, "text": text.strip()})
    candidate["current_task"] = typed_state.task(candidate, after_class=after_class)
    candidate["reply"] = text.strip()
    candidate["last_assistance"] = assistance
    return candidate
