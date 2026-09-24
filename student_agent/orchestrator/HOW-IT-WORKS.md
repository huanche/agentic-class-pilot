# 编排器是怎么转起来的

一份"用大白话讲清编排器运作过程"的说明，配合 `graph_skeleton.py`（LangGraph 骨架代码）看。

> **想直接看能跑的版本？** 在 `agent.py`（真实实现）+ `run_demo.py`（跑一节课）+ `demo-run.md`（运行实录）。
> 本文 + 骨架负责"讲清楚"，那三个文件负责"跑起来"。

---

## 一、一句话概括

编排器就是一个**由表驱动的课堂状态机**：它不生成教学内容，只决定**现在演哪一幕、这一幕还能演多久、什么时候换下一幕**。

```
老师写两张表              AI 每轮做三件事
──────────               ─────────────────
lesson-plan.json   ──→   ① 算：这一幕已经花了多少分钟
（剧目表 + 时长）          ② 问：把当前幕的内容交给大模型去问学生
                         ③ 判：证据够了没？时间到了没？→ 决定换不换幕
```

**输入是一张表，输出是"换不换幕"**。教学内容在别处（`stages/`、`KNOWLEDGE-BASE.md`），编排器只负责调度。

---

## 二、自然语言描述：一轮对话里发生了什么

假设学生刚说了一句话，一轮对话开始。

### 第 1 步：先算时间（`tick`）

编排器第一件事是看表：

> "现在 `10:14`，这一幕从 `10:00` 开始，那这一幕已经演了 **14 分钟**。整节课从 `10:00` 开始，已经过了 **14 分钟**。"

就这么简单。**只看墙上的钟，不数"聊了几轮"**，也不判断学生是不是在座位上。

> 为什么把时间做成一进图就算好？因为如果让每个节点自己去读钟，就会有的地方用 `10:14`、有的地方用 `10:14:03`，数字对不上，还没法测试。现在时间是**从外面送进来的**，图内部只做减法——喂一串时间戳就能把整节课重放一遍，这在测试切幕逻辑时是救命的。

### 第 2 步：装配该看的东西（`load_context`）

不是把整门课塞进大模型的上下文，而是**按当前这一幕需要什么，就只装什么**：

| 装什么 | 什么时候装 |
|---|---|
| 知识点目录、判星规则 | 每轮都装 |
| 课程计划里**当前这一幕**的配置 | 每轮都装 |
| 现在讲的这个片段（segment） | 每轮都装 |
| **复述幕的题目 / 评判标准 / 提示词** | 只在演复述幕时装 |
| 学生的掌握档案 | 只在判星级时装 |

> 这么做的好处：一门 45 分钟的课可能有几十个片段，全塞进去上下文会爆炸。按幕取用，上下文永远是"刚好够用"。

### 第 3 步：这轮谁在说话（`classify_turn`）

分清是**学生**开口了，还是**主持人**（老师/系统）触发了开场、收尾这类事件。两条路走法不同。

### 第 4 步：教学（`teach`）

学生轮就走这里：把上一步装好的上下文交给大模型，让它生成追问、反馈或讲解。产出的东西有两类：

- **回复文本** → 给学生看
- **证据** → 从学生的回答里提取"他到底懂没懂"，交给下一步判星

### 第 5 步：判星级（`judge_mastery`）

对照 `rubric.md` 和星规则，算出这个知识点的星级有没有变化。注意：**这一步只记录，不决定下一幕**。

### 第 6 步：判切幕（`judge_advance`）★ 核心

这是整个编排器唯一"做决定"的地方。它按顺序问几个问题，**一旦命中就停**：

1. **这一幕演够 2 分钟了吗？** 没够 → 留着，别急着换（防秒切）
2. **目标是"学透才走"模式，但还有目标没关掉？** → 留着
3. **证据够了、目标都关掉了？** → 换幕
4. **时间到了预算（比如 22 分钟）？** → 看策略：立刻换 / 收个尾再换 / 还能再给几分钟
5. **以上都没命中** → 留着，继续

> 顺序就是优先级：**先保证不秒切，再保证"学透才走"能拦住时间**，最后才轮到时间说了算。

### 第 7 步：换幕（只有决定换时才走）

换幕要做三件收尾的事：

1. **给刚演完这一幕拍张快照**——记下"这一幕花了多久、关掉了哪些目标、还剩哪些没关"，追加进掌握历史。这样老师能看出学生是一步步怎么变化的。
2. **从剩余剧目里取下一幕**（被老师关掉的幕早就过滤掉了，不会轮到）。
3. **重置本幕状态**：开始时间设成"现在"，计时归零，本幕目标清空。

### 第 8 步：落盘 + 回复

把状态写回 `runtime/`，组装最终回复给学生。然后**等下一轮**。

---

## 三、关键洞察：它为什么能"自动推进"

因为图里有一条**环**。

```
load_plan → tick → load_context → classify_turn
                                      ↓
                                   teach
                                      ↓
                              judge_mastery
                                      ↓
                              judge_advance ──┐
                                      ↓       │
                                 advance_stage ┘  ← 换幕也是走这一圈
                                      ↓
                                 write_state → format_reply → END
```

学生每说一句话，就走这圈一次。**`judge_advance` 每次都重新判一次"该不该换"**。

- 不换 → 这圈走完，下一句话再走一圈，还在同一幕里
- 换 → 顺路去 `advance_stage` 把幕换掉，然后下一句话就在新幕里走了

所以"自动推进"不是有个定时器在后台跑，而是**每一轮对话都在重新评估进度**。学生说 50 句话，就评估 50 次。这就是为什么它既能在学生学得快时提前切幕，又能在时间到点时准时切幕。

---

## 四、落到 LangGraph 里，具体长什么样

代码见 `orchestrator/graph_skeleton.py`。下面是**最关键的四个写法**。

### 4.1 State 是整个图的共享字典

LangGraph 不像普通函数那样"传参"，而是所有节点读写**同一个状态对象**。

```python
class ClassroomState(TypedDict):
    host_phase: Literal["intro", "guided_learning", ...]  # 演到哪了
    stage_elapsed_minutes: float      # 这一幕花了多久
    now: str                          # 本轮时间戳（外面送进来的）
    ...
```

**有一个字段要特别注意：**

```python
    stage_snapshots: Annotated[list[dict], operator.add]
```

普通字段是"覆盖"的——节点返回什么就改成什么。但这个字段加了 `Annotated[..., operator.add]`，意思是**累加**：`advance_stage` 每幕结束返回一条快照，它会**追加**到已有的列表上，历史不会被冲掉。

> 这是新手最容易踩的坑：不加 `Annotated`，第二幕的快照会把第一幕的覆盖掉，掌握历史就只剩一条。

### 4.2 节点就是普通函数，返回"要改的那部分"

```python
def tick(state: ClassroomState) -> dict:
    now = datetime.fromisoformat(state["now"])
    return {
        "stage_elapsed_minutes": minutes_since(state["stage_started_at"]),
        "lesson_elapsed_minutes": minutes_since(state["lesson_started_at"]),
    }
```

三个要点：

- **收一个 `state`，返回一个 `dict`** —— 就这个签名。
- **返回的 dict 只写要改的字段**。没返回的字段保持原值，不需要把整个 state 抄一遍。
- **节点不该有副作用**（除了 `write_state` 落盘那次）。这样才好测。

### 4.3 判断写进 state，路由只读不判

这是这道题最值得学的一个技巧。切幕逻辑本该很复杂，但我们**把它拆成两半**：

```python
def judge_advance(state) -> dict:
    """★ 判定逻辑全在这，结果写进 target_phase"""
    if state["stage_elapsed_minutes"] < min_stage_minutes:
        return {"target_phase": None, "advance_reason": "未达最短幕时长"}
    if ... :
        return {"target_phase": _next_phase(state), "advance_reason": "预算耗尽"}
    return {"target_phase": None, "advance_reason": "未触发"}


def route_after_judge(state) -> str:
    """路由函数只读判决，不重新判断"""
    return "next_stage" if state.get("target_phase") else "stay"
```

为什么这么拆？

- **路由函数必须极简**。LangGraph 里条件边的路由函数只是个"选路器"，业务判断塞进去会很难读、很难测。
- **判定过程可测**。`judge_advance` 是个纯函数，喂 state 出判决，可以直接单测。`clock_reference.py` 就是这么测的。
- **判决有痕迹**。`advance_reason` 落盘后，老师能复盘"这一幕为什么在 22 分钟时切了"。

连接起来：

```python
g.add_conditional_edges(
    "judge_advance",
    route_after_judge,                        # 选路器
    {"stay": "write_state", "next_stage": "advance_stage"},   # 边名 → 去哪
)
```

### 4.4 调用方：每轮注入 `now`，用同一个 `thread_id` 续

```python
config = {"configurable": {"thread_id": session_id}}

graph.invoke(
    {"now": "2026-09-18T10:14:00+08:00",   # ← 时钟从这里进来
     "student_message": "我觉得应该让短作业先跑"},
    config,
)
```

关键点：

- **`now` 由调用方给**，图里任何节点都不许自己读钟。这是"可回放"的前提。
- **`thread_id` = 会话 ID**。配上 checkpointer，同一个学生会话每次 `invoke` 都自动从上一轮的状态继续，不需要把整个 state 重新传一遍。
- **只传这一轮新增的输入**（时间戳 + 学生消息），其余字段从 checkpoint 恢复。

配上 checkpointer 后，进程重启也能接着上——这比直接读写 `DIALOGUE-LOG.md` 多了一层原子性。

---

## 五、这套设计的三个"为什么"

| 设计 | 为什么这么做 |
|---|---|
| **时间外部注入，节点只做减法** | 图变成纯函数，可以喂一串时间戳重放整节课。切幕逻辑才敢改 |
| **切幕判定集中在 `judge_advance` 一个节点** | 进度决策只有一处。散在多处就会出现"这里按证据切、那里按时间切"的混乱 |
| **节点只返回要改的字段** | 避免每个节点都抄一遍整个 state，改动能局部化 |

---

## 六、这份骨架没做的事（真实实现要补）

`skeleton` 里标了 `[占位]` 的地方：

- `teach` / `host_event`：真正调用大模型的逻辑
- `judge_mastery`：对照 `rubric.md` 判星级的逻辑
- `load_context`：按幕取用文件的真实装配（现在只是拼接）
- `write_state`：真正写 `DIALOGUE-LOG.md` 和 `mastery-*.json`
- `classify_turn`：真实判断"谁在说话"（现在靠规则）

**但骨架已经把"编排"这件事讲完了**：状态长什么样、节点怎么写、判断怎么变路由、循环怎么形成。剩下的都是填充。

---

## 七、相关文件

| 文件 | 作用 |
|---|---|
| `orchestrator/ORCHESTRATOR.md` | 权威规范（10 个节点、判定顺序、降级行为、校验清单） |
| `orchestrator/graph_skeleton.py` | LangGraph 骨架代码（本文讲解对象） |
| `orchestrator/clock_reference.py` | 时钟与切幕的可运行参考实现 + 回归测试 |
| `lesson-data/lesson-plan.json` | 老师配的表（剧目 + 时长 + 推进策略） |
