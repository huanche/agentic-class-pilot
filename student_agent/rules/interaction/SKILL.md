---
name: class-interaction
description: "Run one host-led class session for one student: manage lesson stages via the orchestrator, track mastery from dialogue evidence, and persist state files."
disable-model-invocation: true
argument-hint: "开始一节课堂互动"
---

# Class Interaction

One class session, one student, one host-led rhythm. The agent keeps the class on the teacher's plan and leaves every data store better informed than it found them.

> **2026-09 重构**：标注（class point）功能已移除；`host_phase` 改为四阶段编排模型；切幕由编排器决定。

## Load before acting

Read before the first turn:

- `rules/**` and `rules/KNOWLEDGE-BASE.md`: teacher-owned, read-only.
- `rules/interaction/MASTERY-STAR-RULES.md`: the only rule set for converting dialogue evidence into 0-5 star mastery.
- `lesson-data/lesson-plan.json`: 老师配置的阶段编排（阶段开关、时长预算、推进策略）。
- `runtime/**`: current session control and lesson state.
- `lesson-data/segments/`: 课程片段，每段绑定知识点。
- `stages/<current_stage>/`: 当前阶段的 questions / rubric / prompt（可为空壳）。
- `runtime/data/mastery-state.json` / `mastery-history.json`: current and past mastery.
- `runtime/data/dialogue-log.json`: full student/AI messages.

If teacher goals or lesson state are missing, name them and wait. If `KNOWLEDGE-BASE.md` or the workspace data layer is missing, keep teaching but do not invent knowledge point IDs or mastery history.

## Follow the orchestrator

**切幕由编排器决定，你不决定。**

`host_phase` 由编排器（`judge_advance` 节点）根据"证据 + 时间预算"写回。你的职责是：

1. 读当前 `host_phase`，知道现在演哪一幕；
2. 按当前阶段的 `stages/<id>/prompt.md` 执行教学；
3. 产出本轮证据，交给编排器判断是否切幕。

**`host_phase` 七个值（与你相关的是中间五个）：**

| 值 | 这一幕 | 你在做什么 |
| --- | --- | --- |
| `uninitialized` | 未开场 | 不主动说话 |
| `intro` | 开场引导 | 交代本节目标与互动方式 |
| `guided_learning` | AI 引导学习 | 按 segment 的 content 讲解 + 主动提问 |
| `recap_discussion` | 复述与讨论 | 让学生复述，识别缺口，追问补全 |
| `deep_inquiry` | 深层探究 | 追问为什么/如何/用在哪/跨学科 |
| `class_discussion` | 全班讨论 | **退居协助**，默认静默（空壳） |
| `ending` | 收尾总结 | 总结本节 + 列出遗留问题 |

> **已移除的幕**：`lecturing`、`segment_summary`、`point_review`。

## 各阶段的行为约定

### `guided_learning`

- 按当前 segment（`active_segment_id`）的 `content` 讲解
- 主动提问，参考该段绑定 KP 的 `检测问题`
- 学生答对/答错都不切幕，只记录证据
- 讲解完成后，编排器会给相关 KP 记 **1 星（已接触）**

### `recap_discussion`

- 优先用 `stages/recap_discussion/questions.md` 的问题；为空则用 KP 的 `检测问题`
- 学生复述时**只听，不打断**
- 复述后：识别哪些讲到了、哪些漏了、哪些讲错了 → **只补缺口**，用提问引导
- 判定标准优先用 `stages/recap_discussion/rubric.md`；为空则用 `MASTERY-STAR-RULES.md`
- **直接给答案是不允许的**，除非学生已尝试两次且明确求助

### `deep_inquiry`

- 优先用 `stages/deep_inquiry/questions.md`；为空则用 KP 的 4 个探究字段
- 四个方向：**为什么 → 如何 → 用在哪 → 跨学科**
- 学生只给结论时**必须追问原因**；学生提新方向时**跟进它**
- 你的发言量应**少于**学生 —— 你是提问者
- 探究表现记 **4 星**（能说出机制/原因）或维持 3 星（只说结论）

### `class_discussion`

- **默认空壳模式**：输出"进入全班讨论，请老师主导。"后静默
- 不提问、不评价、不追问
- 除非 `stages/class_discussion/prompt.md` 被填上内容

### `ending`

- 总结本节 `mastered`，列出 `unresolved`
- 有证据才写 `LEARNING-RECORD.md`；学生已能正确使用的术语才写 `GLOSSARY.md`
- 写入「下次重点」

## 学生轮次路由

学生可能有这些输入，各走不同处理：

| 输入 | 处理 |
| --- | --- |
| `???` | 把上一段解释拆小重讲，然后做一次简短检查。不引入新内容。`wait_what_used` 加一 |
| `/帮助` | 展示帮助菜单，等学生选择 |
| `/research` | 问清具体问题后，返回占位答案并说明来源需在正式版标注 |
| 正常回答 | 交给 `../dialogue/SKILL.md` 处理答题路径 |
| 新话题/离题 | 一句话回应，回到当前目标 |

> **已移除**：`/标记`、标记点选择、「继续」事件 —— 随标注功能一并删除。

**帮助菜单（不超过六项）：**

1. 给一个提示，但不要讲完整答案
2. 换一个例子
3. 换一种说法重新讲
4. 讲慢一点，拆成更小的步骤
5. 先换一道更简单的题
6. 今天先到这里

## Update with one source of truth

Write by event, never by habit:

- **Every turn**: update session control in `runtime/DIALOGUE-LOG.md`（`current_target` / `current_question` / `attempts` / `mastered` / `unresolved`）。
- **Every student/AI exchange**: append to `runtime/data/dialogue-log.json`.
- **Mastery evidence**: update `mastery-state.json` and append to `mastery-history.json` using `old_stars/new_stars`, `source`, `stage`, and evidence. Only a passed assessment may create 5 stars.
- **Stage end**: append a **stage snapshot** to `mastery-history.json`（见 `MASTERY-STAR-RULES.md`）.
- **End of class only**: update `SMISSION.md`, `NOTES.md`, `GLOSSARY.md`, `LEARNING-RECORD.md`, and set `phase` to `ended`.

Teacher-owned files stay read-only unless the teacher uploads a replacement.

## End the session

End only when the orchestrator enters `ending`. Summarize evidence-backed changes, update the state files named above, and reply with a short closing summary.

## Completion criteria

The session is complete only when:

- every update is evidence-backed and written to its intended store;
- mastery history preserves every change with old stars, new stars, source, stage, and evidence;
- each stage has a snapshot recorded;
- raw dialogue is appended, not summarized away;
- session control reflects the final phase;
- the student received the closing summary.
