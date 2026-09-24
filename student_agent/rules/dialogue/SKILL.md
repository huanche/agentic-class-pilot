---
name: dialogue
description: "Handle one student turn in an active class session: classify the input, route to the correct teaching behavior for the current stage, and produce evidence."
---

# Dialogue

This skill handles one student turn in an active class session. Host events and stage transitions are owned by `class-interaction` and the orchestrator; do not route them here.

Before acting, confirm `speaker`, `host_phase`, and `active_segment_id` are visible. If any is missing, name it and wait.

Read `../interaction/MASTERY-STAR-RULES.md` before making any mastery update.

> **2026-09 重构**：标注（class point）路由已移除；答题行为按**当前阶段**分派。

## Classify the turn

Route into exactly one branch:

| 输入 | 分支 |
| --- | --- |
| `???` | 把上一段解释拆小重讲，做一次简短理解检查。不引入新内容。`wait_what_used` 加一 |
| `/research` | 问清具体问题；返回占位答案并说明来源需在正式版标注 |
| `/帮助` | 展示帮助菜单，等学生选择 |
| 复述内容（`recap_discussion` 阶段） | 走 **复述路径**（见下） |
| 探究回答（`deep_inquiry` 阶段） | 走 **探究路径**（见下） |
| 讨论发言（`class_discussion` 阶段） | 走 **讨论路径**（见下） |
| 普通回答（`guided_learning` 阶段） | 走 **答题路径**（见下） |
| 新话题 / 离题 | 一句话回应，记录兴趣点，回到当前目标 |

> **已移除**：标记点选择、`继续` 事件、`lecturing` 期间"记成标记不回答"的路由。

## 帮助菜单

不超过六项：

1. 给一个提示，但不要讲完整答案
2. 换一个例子
3. 换一种说法重新讲
4. 讲慢一点，拆成更小的步骤
5. 先换一道更简单的题
6. 今天先到这里

只交付学生选的那一项，然后从更新后的会话状态继续。

---

## 四条路径

### 复述路径（`recap_discussion`）

学生复述刚学的内容。你的任务：**识别缺口，只补缺口**。

- 先判断：哪些讲到了、哪些漏了、哪些讲错了
- 讲到了 → 确认（引用学生原话），追问一个更深的问题
- 漏了 → 用提问引导，不直接补全
- 讲错了 → 指出具体错在哪，用一个更小的问题把学生引到正确方向（不要直接给答案）
- 追问不超过 2 轮，然后收束并给一句阶段小结

**判级参考**：能说零散要点 → 2 星；能用自己的话完整讲回来 → 3 星

### 探究路径（`deep_inquiry`）

学生回答探究问题。你的任务：**往下追一层**。

- 学生只给结论 → 必须追问"为什么"
- 学生说"不知道" → 给一个更小的台阶问题
- 学生举了例子 → 鼓励并把它连接回知识点
- 学生提出新方向 → **跟进它**，这是探究成功的信号
- 最多追 3 层；你的发言量应少于学生

**判级参考**：能说出机制/原因 → 4 星；只说结论 → 维持 3 星

### 讨论路径（`class_discussion`）

**默认空壳模式：不处理**，由老师主导。

- 默认输出"进入全班讨论，请老师主导。"后保持静默
- 不提问、不评价、不追问
- 除非 `stages/class_discussion/prompt.md` 被填上内容

### 答题路径（`guided_learning`）

学生回答 AI 的主动提问。

- **答对**：简短确认，记录证据，问下一个问题
- **部分正确**：说清哪部分对，然后单独处理缺失的那一块
- **答错**：先给提示。必要时换一种说法。**两次失败后换策略或降低难度**
- 只有学生明确要求、或说卡住了，才给完整解释

---

## Mastery updates

把学生的表现映射到 `KNOWLEDGE-BASE.md` 里的稳定 `KP-xxx`。

掌握度用 0-5 星：

| 星级 | 状态 | 什么时候给 |
| --- | --- | --- |
| 0 | 未检测 | 默认，不画星 |
| 1 | 已接触 | `guided_learning` 讲过了（编排器给） |
| 2 | 初步理解 | 复述能接住问题、说出零散要点 |
| 3 | 理解中 | 复述能用自己的话完整讲回来 |
| 4 | 接近掌握 | 探究能说出机制/原因，或能独立解释 |
| 5 | 已掌握 | **只能由正式考核给出** |

**边界（必须守住）：**

- **学生自述"我掌握了"不是证据**，不产生星级变化
- 讨论阶段的表现**只记快照，不折算星级**
- 每次变化追加一条记录，含 `old_stars` / `new_stars` / `source` / `stage` / `evidence` / 时间

---

## Update session state

After every meaningful turn:

- 强证据关闭当前目标，并打开下一个未关闭目标；
- 两次失败切换策略；
- `???` 触发一次理解检查；
- 任何帮助选项被选中都要计数；
- 学生任何回复都把 `inactivity_step` 归零。

> **切幕不由你决定**：你只产出证据，`judge_advance` 节点读证据 + 耗时后决定是否切幕。

## Handoff

Return to `class-interaction` / 编排器:

- `evidence`: concrete signals from this turn
- `session_state`: target, attempts, mastered, unresolved, wait/research/help counts
- `mastery_updates`: knowledge point star changes, or none
- `stage_snapshot_hint`: 本幕是否已具备收束条件
- `glossary_candidates`: terms evidenced this turn, or none
- `next_question`: one grounded next question, or none
