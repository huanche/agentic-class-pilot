# 编排器结构规范（LangGraph 版）

本文件定义**主动引导智能体的编排器**：一个由 `host_phase` 驱动、按老师配置的课程计划自动推进的课堂状态机。

> 本文件是**结构与调度约定的权威说明**。内容空壳（复述问题、评判标准、提示词）位于 `stages/` 目录，此处只规定**它们何时被读取、被谁读取、读取后写回哪里**。
>
> 目标：AI 能把一门课在 `total_minutes` 内上完，且每个阶段该做的事有据可依。

---

## 1. 编排器 = 状态机 + 计划配置

```
老师端配置                   运行时状态                  编排器行为
lesson-plan.json   ──→   runtime/DIALOGUE-LOG.md  ──→  每轮读 → 判 → 写
（阶段开关+时长）          （host_phase + 耗时）          （切幕/留幕）
```

| 概念 | 落在哪里 | 谁维护 |
| --- | --- | --- |
| **演哪一幕** | `host_phase` | AI 每轮写回 |
| **这门课有哪些幕** | `lesson-plan.json` 的 `stages[]` | 老师 |
| **每幕演多久** | `lesson-plan.json` 的 `minutes` | 老师 |
| **当前幕演了多久** | `runtime/DIALOGUE-LOG.md` 的 `stage_elapsed_minutes` | AI 每轮更新 |
| **现在几点** | state 的 `now` | **会话层注入**（编排器不自己取时间） |
| **幕怎么演** | `stages/<stage_id>/prompt.md` | 设计者（可空壳） |
| **幕里问什么** | `stages/<stage_id>/questions.md` | 老师（可空壳） |
| **幕的及格线** | `stages/<stage_id>/rubric.md` | 老师（可空壳） |

---

## 2. 状态 Schema（LangGraph `State`）

编排器的状态对象。所有节点读取并返回它的**部分更新**。

```python
from typing import TypedDict, Annotated, Literal
import operator

class ClassroomState(TypedDict):
    # ── 会话标识 ──
    session_id: str
    student_id: str
    lesson_id: str

    # ── 编排器核心（对应 DIALOGUE-LOG.md 字段）──
    host_phase: Literal[
        "uninitialized", "intro", "guided_learning",
        "recap_discussion", "deep_inquiry", "class_discussion", "ending"
    ]
    active_segment_id: str | None
    stage_started_at: str          # ISO8601，本幕开始时刻
    stage_elapsed_minutes: float   # 本幕已花分钟数
    lesson_elapsed_minutes: float  # 本课已花分钟数
    stage_budget_minutes: float    # 本幕预算（来自 lesson-plan）
    remaining_stages: list[str]    # 尚未演出的幕（已按计划过滤 enabled）

    # ── 时钟（方案 B：真实时钟，外部注入）──
    now: str                       # ISO8601，本轮时间戳。由会话侧注入，节点只读
    lesson_started_at: str | None  # ISO8601，本课开始时刻

    # ── 教学状态 ──
    current_target: str | None     # 当前教学目标（难点/易混淆点/KP）
    current_question: str | None   # 当前抛出的问题原文
    attempts: int                  # 本目标的尝试次数
    mastered: list[str]            # 本幕被证据关闭的目标
    unresolved: list[str]          # 本幕仍未关闭的目标

    # ── 学生状态 ──
    student_message: str
    speaker: Literal["host", "student"]
    student_status: Literal["active", "practicing", "waiting", "ended"]

    # ── 证据与掌握 ──
    turn_evidence: list[str]       # 本轮产生的证据
    mastery_updates: list[dict]    # [{kp_id, old_stars, new_stars, source, evidence, stage}]
    stage_snapshots: Annotated[list[dict], operator.add]  # 每幕结束追加一条快照

    # ── 输出 ──
    reply_text: str
    speech_kind: Literal["none", "auto"]  # 是否语音播报
    advance_reason: str | None     # 为什么切幕（写进日志）
```

> **写回磁盘的映射**：`host_phase` / `stage_elapsed_minutes` / `current_target` 等 → `runtime/DIALOGUE-LOG.md`；`mastery_updates` → `runtime/data/mastery-state.json` + `mastery-history.json`；`stage_snapshots` → `mastery-history.json`（带 `stage` 字段）。

> **`now` 为什么在 state 里而不在节点里调 `datetime.now()`**：时钟是外部世界。把它做成**输入**，图就变成纯函数 —— 可单测、可回放（给定一串时间戳能重放整节课）。实现上由会话层每轮把 `now` 塞进 state，图内任何节点都不得自己取时间。这也是方案 B 能被验收的前提。

---

## 3. 节点（Nodes）

每个节点 = 一次职责单一的动作。这 10 个节点就是要实现的目标结构。

| # | 节点名 | 职责 | 读什么 | 写什么 |
| --- | --- | --- | --- | --- |
| 1 | `load_plan` | 载入并校验课程计划 | `lesson-data/lesson-plan.json` | state: `remaining_stages` / `stage_budget_minutes` / 时钟策略 |
| 2 | `tick` | **按真实时钟算已花时长** | state 的 `now` / `stage_started_at` | state: `stage_elapsed_minutes` / `lesson_elapsed_minutes` |
| 3 | `load_context` | 分层装配上下文 | 见第 4 节 | state 不变（组装 prompt） |
| 4 | `classify_turn` | 判断本轮输入类型 | 学生消息 + `host_phase` | state: `speaker` / 路由标记 |
| 5 | `host_event` | 处理主持人事件 | 主持人指令 | state: 目标 `host_phase` |
| 6 | `teach` | 执行本幕教学（大模型节点） | 组装好的上下文 + `stages/<id>/prompt.md` | state: `reply_text` / `turn_evidence` / `current_question` |
| 7 | `judge_mastery` | 按 rubric 判星级 | `stages/<id>/rubric.md` + `rules/interaction/MASTERY-STAR-RULES.md` | state: `mastery_updates` |
| 8 | `judge_advance` | **判定是否切幕**（编排核心·进度） | 见第 5 节 | state: 目标 `host_phase` / `advance_reason` |
| 9 | `write_state` | 落盘所有状态 | state | `runtime/**` / `runtime/data/**` |
| 10 | `format_reply` | 组装回复与播报标记 | state | state: `reply_text` / `speech_kind` |

> **为什么把 `tick` 单独拆出来**：时间计算只有一处，其他地方一律读结果。否则"到底按哪个数算耗时"会散落在三四个节点里，改不动也测不了。

---

## 4. 上下文分层装配（`load_context`）

这是"不把整门课塞进一轮上下文"的关键。**按 `host_phase` 决定加载哪些层。**

| 层 | 内容 | 何时加载 |
| --- | --- | --- |
| **规则层** | `rules/KNOWLEDGE-BASE.md` 目录 + `rules/interaction/MASTERY-STAR-RULES.md` | 每轮 |
| **计划层** | `lesson-data/lesson-plan.json`（仅当前阶段的配置） | 每轮 |
| **课堂层** | `runtime/DIALOGUE-LOG.md` + 当前 `segments/seg-XXX.json` + 该段绑定的 KP 全文 | 每轮 |
| **阶段层** | `stages/<当前阶段>/questions.md` + `prompt.md` + `rubric.md` | 仅当前阶段 |
| **历史层** | `runtime/data/dialogue-log.json` 的相关片段 | 按需召回 |
| **档案层** | `mastery-state.json` / `mastery-history.json` | 仅判星级时 |

**按阶段加载的阶段层文件（重要）：**

| `host_phase` | 加载 `stages/` 下的哪个 |
| --- | --- |
| `intro` | （无） |
| `guided_learning` | （无，用 segment 的 `content`） |
| `recap_discussion` | `stages/recap_discussion/` |
| `deep_inquiry` | `stages/deep_inquiry/` |
| `class_discussion` | `stages/class_discussion/` |
| `ending` | （无） |

> 空壳阶段：若 `stages/<id>/` 下文件为空或缺失，`load_context` **不报错**，注入占位提示 `[本阶段内容未配置]`，教学节点按默认行为运行（见第 7 节）。

---

## 5. 真实时钟：`tick` 节点（方案 B）

整个编排器**只有这一个地方读时间**。它算出这门课和这一幕**真实花了多少分钟**。

### 5.1 为什么用真实时钟

不用"聊了几轮"估算时长，也不让 LLM 猜耗时 —— 直接读墙上时钟。因为"在规定时间内上完课"这个目标，本质就是对真实时间负责。

### 5.2 输入 / 输出

```
输入:  now, stage_started_at, lesson_started_at

输出:  stage_elapsed_minutes   # 本幕已花分钟数 = now - stage_started_at
       lesson_elapsed_minutes  # 本课已花分钟数 = now - lesson_started_at
```

就是这么简单。**没有挂机判定，没有缺席策略** —— 学生是否在场由老师负责，编排器不管。

### 5.3 时间结算伪码

```python
from datetime import datetime

def tick(state: ClassroomState) -> dict:
    now = datetime.fromisoformat(state["now"])

    def minutes_since(t: str) -> float:
        return round((now - datetime.fromisoformat(t)).total_seconds() / 60, 2)

    return {
        "stage_elapsed_minutes": minutes_since(state["stage_started_at"]),
        "lesson_elapsed_minutes": minutes_since(state["lesson_started_at"]),
    }
```

> **可回放性**：时间全部来自 `now` 输入，喂一串时间戳就能重放整节课，切幕逻辑因此可单测。
> 可运行的参考实现 + 回归测试见 `orchestrator/clock_reference.py`。

---

## 6. 条件边与切幕判定（`judge_advance`）

这是编排器"自动推进"的决策点。**每轮对话结束都执行一次。**

```
输入: host_phase, stage_elapsed_minutes, stage_budget_minutes,
      turn_evidence, unresolved, advance_when, advance_policy

判定顺序（短路）:
  1. 若 stage_elapsed_minutes < min_stage_minutes      → 留幕 (return "stay")
  2. 若 advance_when == "evidence" 且 unresolved 非空  → 留幕
  3. 若 turn_evidence 非空 且 unresolved 为空:
       advance_when ∈ {evidence, either} 且 on_evidence_reached=="advance"
                                                        → 切幕 (return "next_stage")
  4. 若 stage_elapsed_minutes >= stage_budget_minutes:
       on_budget_exhausted == "force_advance"           → 切幕
       on_budget_exhausted == "wrap_up"                 → 本幕收尾后切幕
       on_budget_exhausted == "extend"
           且 超时 < max_stage_overrun_minutes          → 留幕（记延长）
           否则                                          → 切幕
  5. 否则 → 留幕
```

**路由表（LangGraph `add_conditional_edges`）：**

```python
def route_after_judge(state: ClassroomState) -> str:
    nxt = state["target_phase"]
    if nxt is None:
        return "stay"
    return "next_stage"

graph.add_conditional_edges(
    "judge_advance",
    route_after_judge,
    {"stay": "write_state", "next_stage": "advance_stage"},
)
```

**`advance_stage` 节点做的事（切幕三连）：**

1. 把当前幕的**阶段快照**追加进 `stage_snapshots`（含 `stage`、`elapsed`、`mastered`、`unresolved`、`stars_snapshot`）
2. 从 `remaining_stages` 取下一幕；**跳过 `enabled: false` 的阶段**（它们在 `load_plan` 阶段就已被过滤掉）
3. 重置 `stage_started_at`（= 本轮 `now`）/ `stage_elapsed_minutes` / `current_target` / `unresolved`，设新 `host_phase`

**「目前能不能上课」的判断**：只要 `lesson-plan.json` 存在且通过第 9 节的校验，`remaining_stages` 就非空，编排器即可开课 —— **阶段内容为空壳不影响开课**，见第 8 节。

---

## 7. 图结构总览

```
START
  │
  ▼
load_plan ──► tick ──► load_context ──► classify_turn
                                            │
                            ┌───────────────┼───────────────┐
                            ▼               ▼               ▼
                      host_event       teach(学生轮)    (其他路由)
                            │               │
                            │               ▼
                            │         judge_mastery ──► judge_advance
                            │                              │
                            └──────────────► judge_advance ─┘
                                               │
                                  ┌────────────┴────────────┐
                                  ▼                         ▼
                            advance_stage                 write_state
                                  │                         │
                                  └────────► write_state ◄──┘
                                               │
                                               ▼
                                          format_reply ──► END
```

**Checkpointer**：用 LangGraph 的 checkpointer 持久化 `ClassroomState`。推荐 SQLite（与 `runtime/` 同级的本地文件），线程 ID = `session_id`。这样即使进程重启，也能从上一轮状态恢复 —— 等价于旧方案的 `DIALOGUE-LOG.md` 落盘，但多了一层原子性。

> `tick` 放在 `load_plan` 之后、`load_context` 之前：先结算时间，后续所有节点读到的都是同一份确定数字。

---

## 8. 空壳阶段的降级行为（保证"现在就能跑"）

**这是本设计的关键约定**：阶段内容可以完全不写，编排器照常运行。

| 缺失的东西 | 降级行为 |
| --- | --- |
| `stages/<id>/questions.md` 为空 | 复述/探究阶段改用 `rules/KNOWLEDGE-BASE.md` 的 `检测问题` 提问 |
| `stages/<id>/rubric.md` 为空 | 判星级只用 `MASTERY-STAR-RULES.md` 的通用标准 |
| `stages/<id>/prompt.md` 为空 | 使用内置默认提示词（见下） |
| `class_discussion` 无内容 | AI 输出提示"进入全班讨论，请老师主导"，然后按 `minutes` 计时，到点切幕 |

**内置默认提示词（各空壳阶段的兜底）：**

| 阶段 | 兜底行为 |
| --- | --- |
| `recap_discussion` | "请用你自己的话复述刚才这一段讲了什么"，然后按学生回答追问 1-2 轮 |
| `deep_inquiry` | 从 KP 的 `为什么/如何` 字段（若有）各取一问；若无，则问"这个知识点能解决什么实际问题" |
| `class_discussion` | 输出"进入全班讨论，请老师主导"+ 计时 |

> 所以：**你现在就可以跑通整条链路**，只是复述/探究的问法比较朴素。等你把 `stages/` 里的内容填上，质量自然提升，不需要改任何代码。

---

## 9. 启动校验清单

编排器开课前依次检查，任一失败则拒绝开课并写入 `runtime/DIALOGUE-LOG.md` 的"本轮证据"：

1. `lesson-data/lesson-plan.json` 存在且 JSON 合法
2. `total_minutes` > 0
3. 启用的阶段 `minutes` 之和 ≤ `total_minutes`
4. `segments[].id` 均能在 `lesson-data/segments/` 找到对应文件
5. 启用的阶段中，**需要阶段目录的阶段**（`recap_discussion` / `deep_inquiry` / `class_discussion`）其 `stages/<id>/` 目录存在
   > `intro` / `guided_learning` / `ending` **不需要** `stages/` 目录 —— 它们分别由系统、segment 内容、总结逻辑驱动
6. `runtime/` 下模板文件齐全（缺失则从 `rules/interaction/*-FORMAT.md` 生成空白模板）
7. `rules/KNOWLEDGE-BASE.md` 存在（缺失则警告但允许开课，只是不能提问）

> **注意**：校验只到"目录/文件存在"这一层。**阶段目录里的文件是空的也算通过** —— 空壳是合法状态，见第 8 节。

8. `advance_policy` 字段齐全，取值合法（`advance_when` ∈ {either, evidence, budget}）

---

## 10. 节点职责总表

> 本仓库**不含 n8n，也不含前端**。以下 10 个节点是要实现的目标结构，与旧实现的对照见 `MIGRATION.md`。

| 节点 | 必须实现 | 说明 |
| --- | --- | --- |
| `load_plan` | 是 | 读 `lesson-data/lesson-plan.json` 并校验 |
| `tick` | 是 | **真实时钟结算**，唯一读时间的地方 |
| `load_context` | 是 | 按 `host_phase` 分层装配上下文 |
| `classify_turn` | 是 | 判断本轮输入类型 |
| `host_event` | 是 | 处理开场/收尾等主持事件 |
| `teach` | 是 | 执行当前阶段的教学（模型调用） |
| `judge_mastery` | 是 | 按 rubric 判星级 |
| `judge_advance` | 是 | **编排核心**，决定是否切幕 |
| `advance_stage` | 是 | 写阶段快照 + 切到下一幕 |
| `write_state` | 是 | 落盘 `runtime/**` 与 `runtime/data/**` |
| `format_reply` | 是 | 组装回复文本与播报标记 |

**没有的东西（不要实现）**：任何标注相关节点、任何 n8n 节点、任何前端页面。

