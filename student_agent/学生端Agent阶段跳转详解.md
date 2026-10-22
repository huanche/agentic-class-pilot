# 学生端 Agent 阶段跳转详解

本文对应当前工作区的 `student_agent` 实现。先看 [Archify 交互流程图](../.archify/workflow-student-agent-stages-20261022-185608/student-agent-stages.html)，再按下面的代码位置阅读。代码尚在工作区中，文件行号可能随着修改变化，以函数名查找最可靠。

## 1. 先分清两种“阶段”

| 状态 | 存放位置 | 可能的值 | 控制什么 |
| --- | --- | --- | --- |
| 页面阶段 `session["phase"]` | `backend/main.py` 的课堂会话 | `idle`、`video`、`discussion`、`done` | 显示视频、对话框还是反馈页 |
| Agent 阶段 `session["dialogue"]["stage"]` | `agent/progression.py` 的对话状态 | `recall`、`reinforce`、`discuss`、`wrapup` | AI 当前引导复述、补强、讨论还是总结 |

**关键区别：** 页面进入 `discussion` 后不再换页面。Agent 在同一个对话框内部切换四个子阶段。`phase` 不会因 `recall → reinforce` 而改变；变化的是 `dialogue.stage`。前端通过接口返回的 `agentStage` 显示当前子阶段和左侧进度条。

## 2. 从视频到第一次复述

入口在 `backend/main.py`：

1. `begin()` 接收“开始上课”，马上保存 `phase="video"`、`preparation="pending"`，并调用 `schedule_preparation()`。前端可立即播放视频。
2. `prepare_in_background()` 在后台读取已发布视频的材料，`prepared_dialogue()` 调用 `learning_points()` 提取可复述的知识点，再用 `initial_state(points)` 创建 Agent 状态。
3. `initial_state()` 将 `stage` 设为 `recall`。`normalize()` 为每个知识点设置轮数、是否完成、是否排除讨论等字段。
4. 学生点击“进入复述与讨论”时，`discussion()` 保存 `phase="discussion"`，并用 `opening()` 给出首条 AI 消息。开场会列出知识点，并明确“现在进入【初始复述】”。

相关核心代码：

```python
# agent/graph.py
def initial_state(points: list[dict]) -> DialogueState:
    return normalize({
        "stage": "recall",
        "points": [dict(p, status="unseen", attempts=0, evidence="") for p in points],
        "messages": [], "student_text": "", "evaluation": {},
        "reply": "", "strategy": "ask", "discussion_turns": 0,
    })
```

这里的 `normalize()` 不只是补默认值：它把旧版本保存的对话状态转换为当前结构，并在旧讨论轮数达到上限时将阶段归一为 `wrapup`。正常新课堂不会在每轮重置计数。

## 3. 每条学生消息走什么路径

课堂接口在 `backend/main.py` 的 `message()`。它先检查外层 `phase == "discussion"`，调用 `normalize()` 取得当前内层阶段。若已是 `wrapup`，拒绝继续课堂对话，提示学生查看反馈。否则将学生发言加入 `dialogue.messages`，调用 `dialogue_graph.invoke(dialogue)`。

LangGraph 的图在 `agent/graph.py`：

```python
builder = StateGraph(DialogueState)
builder.add_node("evaluate", evaluate)
builder.add_node("route", route)
builder.add_node("respond", respond)
builder.add_edge(START, "evaluate")
builder.add_edge("evaluate", "route")
builder.add_edge("route", "respond")
builder.add_edge("respond", END)
dialogue_graph = builder.compile()
```

这是一条固定节点链：**评估 → 规则跳转 → 生成回复**。`route()` 内部调用 `progression.advance()`；LangGraph 本身并没有让大模型选择下一条边。这里所谓“跳转”，指 `advance()` 修改共享状态中的 `stage`，下一次 `respond()` 按新阶段工作。

```python
# agent/graph.py
def route(state: DialogueState) -> dict:
    return advance(state)
```

一次成功调用后，`message()` 把学生消息、AI 消息和完整 `dialogue` 一起交给 `commit()`；失败时返回 503，不会提交这轮新状态，因此失败的请求不会消耗一轮。

## 4. AI 负责“评估”，代码负责“决定阶段”

`evaluate()` 把当前阶段、当前需要处理的知识点、最近八条消息和本轮学生发言传给模型。初始复述与加强复述只评估 `current_point()` 选出的一个知识点；深入讨论只评估 `eligible_points()` 返回的知识点。

模型必须返回指定 JSON：

```json
{
  "intent": "answer",
  "assessments": [
    {"id": "当前知识点ID", "result": "partial", "evidence": "学生本轮回答中的依据"}
  ]
}
```

`intent` 可以是 `answer`、`question`、`unclear`；结果可以是 `mastered`（掌握）、`partial`（部分理解）、`misconception`（误解）、`unanswered`（明确不会）。`evaluate()` 会检查 ID 是否属于本轮允许评估的知识点、结果是否在允许列表内。无效 ID 和无效结果不会进入阶段决策；整体 JSON 格式不对则本轮失败。

评估规则写在 `agent/prompts.py` 的 `EVALUATION_PROMPT`。它要求不能仅凭学生说出概念名、复述 AI 刚讲过的答案或说“懂了”就判为掌握。模型的结果仍可能有判断误差；轮数与阶段顺序是代码保证的，知识理解质量取决于模型评估。

## 5. 代码怎样选“当前知识点”

`agent/progression.py` 的 `current_point()` 按顺序找第一个尚未完成的点：

```python
def current_point(state: dict) -> dict | None:
    stage = state["stage"]
    if stage == "recall":
        return next((p for p in state["points"] if not p["recall_done"]), None)
    if stage == "reinforce":
        return next((p for p in state["points"]
                     if p["status"] != "mastered" and not p["reinforce_done"]), None)
    return None
```

所以初始复述不会因为学生提前提到后面的概念而跳过当前概念。加强复述只处理首轮仍未掌握的点。进入深入讨论时，程序用 `eligible_points()` 生成固定的知识点队列；`current_point()` 根据 `discussion_point_ids[discussion_index]` 锁定本轮唯一的讨论点：

```python
def eligible_points(points: list[dict]) -> list[dict]:
    return [p for p in points
            if p["status"] == "mastered" and not p["excluded_from_discussion"]]
```

`excluded_from_discussion` 是加强复述到上限仍未掌握时设置的标志。导师的讨论提示词也明确要求不能围绕这些点出题。

## 6. 核心阶段跳转规则

`agent/progression.py` 的 `advance()` 每轮读取 AI 的 `evaluation.assessments`，更新当前点的 `status`、`assessment_history`、复述轮数、是否完成和 `transition`。默认上限为初始复述每点 **8 轮**、加强复述每点 **4 轮**，可分别通过 `STUDENT_AGENT_RECALL_ROUNDS`、`STUDENT_AGENT_REINFORCE_ROUNDS` 设置。深入讨论改为**每个已掌握知识点一题**，不再使用全局 4 轮上限。队列与进度保存在状态中，刷新后继续。

掌握时提前完成当前点：

```python
if outcome == "mastered":
    point["mastered_in"] = stage
    point["recall_done"] = point["reinforce_done"] = True
    result["transition"] = "mastered_next"
```

未掌握且达到本阶段上限时：

```python
elif point[counter] >= result["recall_round_limit" if stage == "recall"
                              else "reinforce_round_limit"]:
    point["recall_done" if stage == "recall" else "reinforce_done"] = True
    point["excluded_from_discussion"] = stage == "reinforce"
    result["transition"] = "defer" if stage == "recall" else "record_gap"
```

首轮耗尽时只是标记 `recall_done=True`，该点在加强复述再次出现。加强轮数也耗尽时标记 `reinforce_done=True`，并排除深入讨论。首轮超过 5 轮仍未掌握会设置 `extended_reinforcement=True`，`STAGE_PROMPTS["reinforce"]` 指示 AI 用更简单的表述或类比重新讲清概念。

所有知识点处理完后，`next_stage()` 按优先级判断：

```python
def next_stage(points: list[dict]) -> str:
    if any(not p["recall_done"] for p in points):
        return "recall"
    if any(p["status"] != "mastered" and not p["reinforce_done"] for p in points):
        return "reinforce"
    return "discuss" if eligible_points(points) else "wrapup"
```

这意味着必须先走完**所有知识点的首轮复述**，才能进入加强复述；加强只处理薄弱点。若没有薄弱点就跳过加强；若没有可讨论的已掌握点就直接进入课堂总结。

讨论阶段只把当前队列知识点交给评估模型。学生对本题作答并得到有效评估后，`discussion_index` 加一，AI 再对下一个点出题；仅求助或说法不清时保留原题。最后一个点完成后阶段变成 `wrapup`。讨论中新发现的问题会记录到反馈，不会重新跳回初始复述。

```python
if stage == "discuss":
    if active and active["id"] in evaluations:
        result["discussion_index"] += 1
        result["discussion_turns"] += 1
    if result["discussion_index"] >= len(result["discussion_point_ids"]):
        result.update(stage="wrapup", completion_reason="all_points_discussed")
else:
    result["stage"] = next_stage(points)
    if result["stage"] == "discuss":
        result["discussion_point_ids"] = [p["id"] for p in eligible_points(points)]
        result["discussion_index"] = 0
if result["stage"] != stage:
    result["transition"] = "enter_" + result["stage"]
```

**注意：** 达到 `wrapup` 只是完成课堂对话，还不是数据库里的课堂结束。学生点击“结束本课并查看反馈”后，`backend/main.py:end()` 才生成逐知识点反馈并保存 `phase="done"`。用户也能提前结束，此时未完成的知识点标记为“评估未完成”或“尚未评估”。

## 7. 阶段变化怎样影响 AI 的话

`agent/graph.py:respond()` 按**跳转后的** `state["stage"]` 取 `STAGE_PROMPTS[stage]`，再叠加 `STRATEGY_PROMPTS[state["strategy"]]`。因此同一个对话框会随着状态使用不同教学任务：

- `recall`：让学生按顺序用自己的话解释，不先出应用题。
- `reinforce`：只补强未掌握的点，必要时换说法、拆小问题。
- `discuss`：每次只围绕队列中的当前知识点提一个应用、比较或推理问题。
- `wrapup`：直接生成固定结束提示，不再调用导师模型出题。

当 `transition` 是 `enter_reinforce` 或 `enter_discuss` 时，程序会在模型回复**前面**加上“现在进入【加强复述】”或“现在进入【深入讨论】”，避免模型忘记提醒。`wrapup` 则给出“现在进入【课堂总结】”和查看反馈的按钮提示。初始复述提醒来自 `opening_message()`。

## 8. 状态怎样保存与恢复

`backend/main.py:commit()` 先构造新会话，再调用 `agent/persistence.py:save()`，成功后才更新内存。正式平台会话通过 `agent/database.py` 把消息写入 `student.student_messages`，掌握度写入 `student.knowledge_mastery`，把包含 `dialogue.stage`、全部知识点、轮数和历史消息的快照写成 `student.learning_events` 中 `event_type='agent_state'` 的事件。

页面刷新或服务重启后，`get_session()` 在内存未命中时调用 `persistence.restore(sid)`，读取最近的 `agent_state` 快照。`state(session)` 返回 `agentStage` 和 `learningProgress` 给前端。前端 `StudentApp.js` 把 `agentStage` 传给 `LessonProgress.js`，于是左侧阶段条可恢复到当前阶段。

```python
# backend/main.py
def state(session: dict) -> dict:
    dialogue = normalize(session["dialogue"]) if session.get("dialogue") else None
    return {
        "phase": session["phase"],
        "agentStage": (dialogue or {}).get("stage"),
        "learningProgress": progress(dialogue) if dialogue else None,
        # 其余课程、消息、反馈字段省略
    }
```

课堂结束时 `lesson_feedback()` 依据真实评估记录生成“掌握较好、加强后掌握、仍需巩固、评估未完成、尚未评估”等逐点反馈，并通过 `lesson_feedback` 事件和完成快照一起保存。`student_agent/agent/persistence.py` 的演示模式没有平台身份，不写这些正式学习表。

## 9. 从哪里开始读代码

建议按这个顺序打开：

1. [`backend/main.py`](backend/main.py)：`begin()`、`discussion()`、`message()`、`end()`，看接口什么时候调用 Agent。
2. [`agent/graph.py`](agent/graph.py)：`initial_state()`、`evaluate()`、`route()`、`respond()` 与 LangGraph 节点链。
3. [`agent/progression.py`](agent/progression.py)：`current_point()`、`next_stage()`、`advance()`，这是跳转规则的核心。
4. [`agent/prompts.py`](agent/prompts.py)：不同阶段的教学提示词及评估格式。
5. [`agent/persistence.py`](agent/persistence.py)：对话、掌握度和状态快照的数据库读写。
6. [`frontend/src/components/StudentApp.js`](frontend/src/components/StudentApp.js) 与 [`LessonProgress.js`](frontend/src/components/LessonProgress.js)：展示当前阶段、阶段进度和结束按钮。

一句话记住：**数据库保存当前状态，LangGraph 每轮依次评估、跳转和回复；模型判断回答质量，`progression.py` 决定真正的阶段跳转，前端只负责显示状态。**
