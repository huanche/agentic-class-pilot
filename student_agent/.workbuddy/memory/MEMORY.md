# 主动引导智能体 — 项目长期笔记

## 项目定位
本项目 = `Dify 课堂互动智能体`(GitHub: HELLO-APL/Dify-Classroom-Interactive-Agent)的重构版。
旧仓库 `D:\project\Dify 课堂互动智能体` **保留不动**,只作参照;重构产物落在本目录,已 git init(首个提交 a0ca473)。

## 核心设计约定(2026-09-17 用户确认)
- **编排器** = `runtime/DIALOGUE-LOG.md` 的 `host_phase` 状态机 + 老师端配置 `lesson-data/lesson-plan.json`。AI 每轮读计划→判证据+判耗时→写回切幕,把一门课在规定时间内上完。
- 阶段枚举:intro / guided_learning / recap_discussion / deep_inquiry / class_discussion / ending。**阶段可按课程启停**(`enabled:false` 整段跳过),每阶段有 `minutes` 时长预算。
- `advance_when` 三值:either(证据或时间)/ evidence(学透才走)/ budget(只看时间)。
- **学生标注功能永久移除**:point_review 幕、points/*.json、1星"已标注"、source=class_point、annotation_ids、「继续」事件。
- **1 星改名为"已接触"**(AI 讲过即记),使星级在无标注情况下保持 0-5 连续。
- **掌握评分靠后三阶段表现阶段性记录**:复述(2-3星)、探究(4星)、讨论(只记快照)。新增 stage_snapshot 机制写入 mastery-history.json。
- 三阶段内容独立成 `stages/<stage>/`:questions.md(老师出题)/ rubric.md(评判标准)/ prompt.md(AI提示词),**可空壳,留空不影响运行**(有降级兜底)。
- `KNOWLEDGE-BASE.md` 新增 4 个探究字段:为什么这样设计/如何实现/解决什么实际问题/关联学科 —— 这是深层探究阶段唯一燃料。
- "区分问题" 概念**已废弃**(2026-09-17):不再出现于任何格式要求中。易混淆点仅在 `TMISSION.md` 列 A vs B 名称,不写提问方式。
- **复述/探究阶段的提问链路**:`stages/<stage>/questions.md`(老师出题,现为空) → 为空则降级用 `runtime/TMISSION.md` 的 `检验问题`(已补齐 4 条,挂 KP 编号) → 再降级用 `rules/KNOWLEDGE-BASE.md` 的 `检测问题`。三级兜底,保证空壳也能上课。
- 目录用无空格英文名:rules/ lesson-data/ runtime/ apps/ stages/ orchestrator/ workflow/。
- 旧用户运行时记录不迁移,runtime/ 与 workspace data 用空白模板初始化。

## 编排器时钟约定（2026-09-18 确认方案 B）
- **真实时钟，不靠 LLM 估算时长**。`now` 由会话层**注入 state**，图内节点一律不调 `datetime.now()` → 图是纯函数，可单测可回放。
- **新增 `tick` 节点**（总计 10 个节点）：所有时间计算集中于此，是唯一读时间的地方。
- **时钟只算已花时长，仅此而已**：
  `stage_elapsed_minutes = now - stage_started_at`，`lesson_elapsed_minutes = now - lesson_started_at`。
- ⚠️ **编排器绝不判断学生是否缺席**（2026-09-18 用户明确要求）。
  曾误加 `clock_policy`（挂机判定/缺席策略/净时长折算），已全部删除。
  学生是否在场是老师的事；编排器引入这类判定只会让切幕变得不可预测。
  不要以任何理由重新引入 absent / idle / 有效时长折算等概念。
- 本地无 `datetime.now()` 依赖，便于测试。

## 关键文件
- `orchestrator/ORCHESTRATOR.md` — LangGraph 编排规范(State schema / 11 节点 / tick 时钟 / judge_advance 判定 / 分层装配 / 降级行为 / 校验清单)
- `orchestrator/agent.py` — **真实 LangGraph 实现**（11 节点，可跑）。LLM 可插拔：
  配置 `AGENT_LLM_BASE_URL` / `AGENT_LLM_API_KEY` / `AGENT_LLM_MODEL`（任意 OpenAI 兼容端点）后
  `teach` 调真模型；未配置则走降级脚本。**`judge_mastery` 始终确定性**（证据组关键词匹配），星级不依赖模型。
- `orchestrator/llm_probe.py` — 端点探针。**必须先用它验证再跑整节课**：teach 在 LLM 失败时静默降级，
  整节课照样跑完，所以"跑通了"≠"接上了"。
- `orchestrator/demo-run.md` — 接 DeepSeek 真模型的运行实录
- `orchestrator/run_demo.py` — 模拟一节课（19 轮带时间戳），`demo-run.md` 是真实运行实录
- `orchestrator/HOW-IT-WORKS.md` — 大白话运作过程说明 + 关键 LangGraph 写法
- `orchestrator/graph_skeleton.py` — LangGraph 骨架代码(11 节点签名 + 建图 + 路由)，非完整实现
- `orchestrator/clock_reference.py` — 时钟与切幕的可运行参考实现 + 11 条回归测试
- `orchestrator/MIGRATION.md` — 新旧路径映射与变更记录
- `rules/interaction/MASTERY-STAR-RULES.md` — 0-5 星唯一权威规则
- `lesson-data/lesson-plan.json` — 老师端编排入口

## 真实实现补充的约定（2026-09-18）
- **`tick` 兼做每轮复位点**：清 `turn_evidence` / `mastery_updates` / `target_phase` / `advance_reason`。
  这些字段跨 checkpoint 持久化，不复位上一轮判决会渗进本轮判定。
- **未关闭目标 `unresolved` 带入下一幕**：复述没答透的 KP，探究阶段优先追问（`advance_stage` 的 `carried`）。
- **讲解阶段 `unresolved` = 全部段落 KP**（讲过 ≠ 关闭），快照才有意义。
- **提问三级链的坑**：`stages/*/questions.md` 里"填写格式/示例"在 code fence 内，解析前必须剥掉，
  否则会把示例当真题。当前实际生效路径是第 2 级（`TMISSION.md 检验问题`）。
- `langgraph-checkpoint-sqlite` 本机装不上，checkpointer 用 `InMemorySaver`；SQL 版待装包后替换。

## 关键 LangGraph 写法约定
- **判断写进 state，路由只读不判**：`judge_advance` 做全部判定并把结果写 `target_phase`；
  `route_after_judge` 只 `return "next_stage" if target_phase else "stay"`。
  好处：路由函数极简、判定可单测、判决有痕迹(`advance_reason`)。
- **`stage_snapshots` 必须用 `Annotated[list[dict], operator.add]`**：否则第二幕快照会覆盖第一幕。
- **节点签名统一 `(state) -> dict`，只返回要改的字段**，不返回的保持原值。
- **自动推进的本质是图里有一个环**：每轮对话重新评估一次，不是后台定时器。

## ★ teach 必须是两层（2026-09-18 实测踩出来的架构铁律）
- **第一层 确定性骨架**（永远执行）：决定讲哪一段 / 问哪一题 / 给什么反馈 → 产出 `directive`
- **第二层 LLM 润色**（可选）：只把 directive 变成自然语言；失败就用骨架的朴素文案
- **铁律：模型不决定讲什么、问什么，只决定怎么措辞。**
  最初写成"有 LLM 就调模型然后 return" → 段落不推进、问题不挂起、证据不匹配 → **编排器被架空**。
- 三条约束（每条都是实测踩出来的）：
  1. `directive` **必须带内容锚点** —— 曾只写"往深讲一层"，模型编出了本课没有的"马尔可夫性质"（幻觉）
  2. 传给模型的文案**不能有 KP 编号** —— 模型会照着念。用 `kp_title()` 转中文标题
  3. 收尾轮 directive 要**显式禁止新内容**
- 验证方式：有/无 LLM 跑同一串时间戳，剔除 `reply_text` 后编排结果应逐行相同（已验证 51/51）。
- ⚠️ 接 LLM 后**不再逐字节可回放**（模型输出不确定）。可回放性只在降级模式成立——
  它来自时钟注入，与逐字回放是两件事。

## 环境备注
- 本机 bash 的 PATH 缺 dirname/ls 等，需 `export PATH="/usr/bin:/bin:$PATH"` 修复；PowerShell stdout 会吞输出，优先用 bash+文件落盘。
- **Git Bash 的 `/tmp` = `C:\Users\陈怡凡\AppData\Local\Temp`**；用 Python 读 /tmp 下的文件必须转成
  Windows 路径（`cygpath -w /tmp`），否则报 `can't open file`。
- workbuddy.link 分享页数据可从 workbuddy-space-static.codebuddy.work/page/<id>/0/conversation-data.json 直接拉取。
- **langgraph 已装**：`pip install langgraph` 成功（1.2.11），装在隔离环境
  `C:/Users/陈怡凡/.workbuddy/binaries/python/envs/default/`（早期会话里"离线装不上"已过期）。
  `langgraph-checkpoint-sqlite` 仍装不上（镜像无此包）。
  装不上依赖时验证图拓扑的替代手法：伪造 `langgraph.graph.StateGraph` 桩，记录
  add_node/add_edge/add_conditional_edges 调用后断言。
- 隔离 Python 环境: `C:/Users/陈怡凡/.workbuddy/binaries/python/envs/default/`
- **同一文件禁止并行 Edit**：并发多条 Edit 打到同一文件时，后写的会覆盖先写的，
  表现为"代码来回变、刚改的又没了"（2026-09-18 在 `agent.py` 中招三次）。
  同一文件的多处修改必须串行一条条改。
- **`pip install` 必须绕开清华源**：pip 走 `pypi.tuna.tsinghua.edu.cn` 会报
  "from versions: none"（curl 却能拿到页面）。用
  `pip install -i https://pypi.org/simple --trusted-host pypi.org`。
  fastapi / uvicorn 就是这样装上的。

## 会话层（apps/）约定（2026-09-21 新增）
- **职责边界**：编排（讲什么/问什么/何时切幕/打几星）只在 `orchestrator/agent.py`；
  `apps/server.py` 只做四件事：持有会话状态、跑心跳时钟、收发消息、导出学情。
  在会话层写任何教学判断都会让编排结果不可预测。
- **心跳 = `tick_only` 的一个轮次**，不改编排语义。路由让心跳走 `teach`（否则讲解阶段不会
  自动推进段落）；开不开口由 teach 按"有没有新内容"决定：新段落 / 新一问 → 说，
  同一段 / 问题已挂起等答 / ending → 静默。`tick` 每轮必须清空 `reply_text`，
  否则静默轮会把上一句重复推给前端。
- **不用 checkpointer**：`langgraph-checkpoint-sqlite` 装不上；`load_plan` 幂等，
  故用 `run_turn_stateless()` 每轮全量回灌上一轮 state，持久化只写
  `runtime/sessions/<sid>.json`。
- **`time_scale` 由会话层注入 state**（不是读环境变量），保持图是纯函数。
  `?scale=30` 把 45 分钟课压到约 90 秒，课前彩排用；倍速越大心跳采样越粗，会跳过段落。
- **切幕/下课要说人话**：别把 `[切幕] 进入X（预算 n 分钟）` 这类内部日志写进 reply_text，
  模型会照念。用 `stage_opening()` / `_ending_remark()`（LLM 润色 + 模板兜底）。
  下课总结必须在 `advance_stage` 当场生成——切到 ending 会立刻置 `student_status=ended`
  停心跳，等下一轮 teach 说就永远没人说了。
- **真实时钟的副作用**：电脑休眠后唤醒，课时会按真实时间跳变直接走到下课。上课前别休眠。
- **已知未做**：多人会话不隔离（见 README 已知缺口）——`write_state` 落盘路径写死，
  全班同时用会互相覆盖掌握档案。
