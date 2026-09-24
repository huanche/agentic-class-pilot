# DIALOGUE-LOG Format

`DIALOGUE-LOG.md` 是**当前会话的控制块**，也是编排器读写的核心状态文件。

原始学生/AI 消息存在 `runtime/data/dialogue-log.json`；掌握度存在 `mastery-state.json` / `mastery-history.json`。

> **2026-09 重构说明**：`host_phase` 枚举已更新（移除 `point_review`、新增三个阶段），并新增**编排器字段**（阶段预算、耗时、切幕原因）。

---

## Template

```md
# DIALOGUE-LOG

## 会话状态
- student_id: {student id}
- lesson_id: {lesson id}
- speaker: {host | student}

### 编排器
- host_phase: {uninitialized | intro | guided_learning | recap_discussion | deep_inquiry | class_discussion | ending}
- active_segment_id: {segment id or 无}
- now: {ISO8601 本轮时间戳，由会话层注入}
- lesson_started_at: {ISO8601 or 无}
- stage_started_at: {ISO8601 or 无}
- stage_elapsed_minutes: {number}
- lesson_elapsed_minutes: {number}
- stage_budget_minutes: {number}
- remaining_stages: {尚未演出的阶段列表}
- advance_reason: {为什么切幕 or 无}

### 教学
- phase: {未初始化 | dialogue | ended}
- current_target: {难点 | 易混淆点 | 知识点}
- current_question: {exact open question or 无}
- attempts: {number}
- mastered: {本幕被证据关闭的目标}
- unresolved: {本幕仍未关闭的目标}

### 学生
- student_status: {active | practicing | waiting | ended}
- wait_what_used: {count}
- research_used: {count}
- help_used: {count}
- inactivity_step: {0 | 1 | 2 | 3}

## 本轮证据
- {evidence}

## 下次重点
- {evidence-backed next focus}
```

---

## host_phase 新枚举说明

| 值 | 这一幕 | 由什么推进进来 |
| --- | --- | --- |
| `uninitialized` | 未开场 | 系统初始状态 |
| `intro` | 开场引导 | 系统自动 |
| `guided_learning` | AI 引导学习（0-50%） | 上一幕结束 |
| `recap_discussion` | 复述与讨论（50-70%） | 上一幕结束 |
| `deep_inquiry` | 深层探究（70-85%） | 上一幕结束 |
| `class_discussion` | 全班讨论（85-100%） | 上一幕结束 |
| `ending` | 收尾总结 | 上一幕结束 |

> **已移除**：`lecturing`、`segment_summary`、`point_review`。
> `point_review`（标记点答疑）随标注功能一并删除。

---

## 编排器字段说明

| 字段 | 谁写 | 作用 |
| --- | --- | --- |
| `now` | **会话层注入** | 本轮时间戳。编排器不自己取时间，保证可单测、可回放 |
| `lesson_started_at` | 编排器（开课） | 本课开始时刻 |
| `stage_started_at` | 编排器（切幕时） | 本幕开始时刻 |
| `stage_elapsed_minutes` | 编排器（`tick`） | 本幕已花分钟数 = `now - stage_started_at` |
| `lesson_elapsed_minutes` | 编排器（`tick`） | 本课已花分钟数 = `now - lesson_started_at` |
| `stage_budget_minutes` | 编排器（读 plan 时） | 本幕预算，来自 `lesson-plan.json` |
| `remaining_stages` | 编排器（切幕时） | 尚未演出的阶段，`enabled: false` 的已被过滤 |
| `advance_reason` | 编排器（切幕时） | 记录为什么切幕，便于老师复盘 |

> **编排器只算时间，不管学生是否在场。** 学生有没有在听课由老师负责，不需要编排器判定。挂机、缺席、有效时长折算等概念一律不引入 —— 只会让切幕逻辑变得不可预测。

---

## Rules

- 只记录**会话控制与证据**，不记录每一条消息。
- 原始对话追加到 `dialogue-log.json`，不在这里重复。
- 掌握度变化写入 `mastery-state.json` / `mastery-history.json`，不以此文件为准。
- 本文件的 `mastered` / `unresolved` 只描述**本幕目标**，不是全局掌握档案。
- `???` 使 `wait_what_used` 加一。
- 无法说明来源的问题，不得写成有依据的证据。
- 下次重点必须指向老师目标、课程文件或知识点。
- **切幕只能由编排器（`judge_advance`）决定**，教学节点不得自行改 `host_phase`。
