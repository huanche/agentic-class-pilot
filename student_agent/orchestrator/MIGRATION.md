# 从旧仓库迁移的映射与变更记录

> 迁移日期：2026-09-17（2026-09-18 修订：移除 n8n 与前端，废弃区分问题，`LESSON-INTERACTION` 改名，编排器改用真实时钟）
> 源仓库：`D:\project\Dify 课堂互动智能体`（**保持不动，仅作参照**）
> 目标仓库：`D:\project\主动引导智能体`（本仓库）
> 上游：`HELLO-APL/Dify-Classroom-Interactive-Agent`

---

## 一、路径映射表

| 旧路径 | 新路径 | 处理 |
| --- | --- | --- |
| `class agent/` | `rules/` | 目录改名（去掉空格） |
| `class agent/class-interaction/` | `rules/interaction/` | 改名 + 内容改造 |
| `class agent/dialogue/` | `rules/dialogue/` | 改名 + 内容改造 |
| `class agent/KNOWLEDGE-BASE.md` | `rules/KNOWLEDGE-BASE.md` | **新增 4 个探究字段** |
| `class-point/segments/` | `lesson-data/segments/` | 原样迁移 |
| `class-point/points/` | — | **不迁移**（标注功能移除） |
| `teach test/` | `runtime/` | 改名 + 重置为空白模板 |
| `teach test/LESSON-INTERACTION.md` | `runtime/LESSON-CONTENT.md` | **改名**（旧名太宽泛）+ 移除易混淆点段 |
| `classroom-chat/` | — | **不迁移**（不做前端） |
| `student-workspace/` | — | **不迁移**（不做前端） |
| `workflow/` | — | **不迁移**（不要 n8n） |
| `docs/` | — | **不迁移**（待重写） |
| `archive/` | — | **不迁移**（旧实验，留在旧仓库） |
| `start-classroom-chat.cmd` | — | **不迁移**（启动前端用，已无前端） |
| — | `runtime/data/` | **新建**：掌握度与对话流水（原属 student-workspace） |
| — | `lesson-data/lesson-plan.json` | **全新**（编排入口） |
| — | `stages/` | **全新**（三阶段内容层） |
| — | `orchestrator/ORCHESTRATOR.md` | **全新**（LangGraph 编排规范） |

---

## 二、内容迁移明细

### 原样迁移（内容保留）

| 文件 | 说明 |
| --- | --- |
| `lesson-data/segments/seg-001~006.json` | 课程片段，属课程内容而非用户记录 |
| `rules/KNOWLEDGE-BASE.md` | 知识点正文保留，仅追加 4 个空探究字段 |
| `runtime/TMISSION.md` | 老师写的第3章目标与难点，**内容完整保留** |
| `runtime/LESSON-CONTENT.md` | 本课先修/新内容/任务/成功证据/材料来源，**保留**；**已删除「易混淆点」段** |

> `TMISSION.md` 与 `LESSON-CONTENT.md` 是**老师课程内容**，不是用户运行时记录，所以迁移。
> `TMISSION.md` 还缺新增的 `检验问题` 字段，待老师补充。

### 重置为空白模板（旧数据丢弃）

按"用户运行时记录可直接删除"：

| 文件 | 旧内容 | 新状态 |
| --- | --- | --- |
| `runtime/DIALOGUE-LOG.md` | 旧会话状态（lecturing / seg-002） | 空白初始状态（uninitialized） |
| `runtime/SMISSION.md` | 旧学生目标 | 空白模板 |
| `runtime/NOTES.md` | 旧工作观察 | 空白模板 |
| `runtime/GLOSSARY.md` | 旧词汇 | 空白模板 |
| `runtime/LEARNING-RECORD.md` | 旧记录 | 空白模板 |
| `runtime/data/*.json` | 旧掌握/对话数据 | 空白模板 |
| `class-point/points/*.json` | 标记点 | **不迁移** |

---

## 三、功能变更

### 移除：学生标注

| 移除项 | 原位置 |
| --- | --- |
| 标记点数据 | `class-point/points/*.json` |
| `point_review` 幕 | `class agent/class-interaction/SKILL.md` |
| 「继续」事件与固定收尾语 | 同上 + `dialogue/SKILL.md` |
| 标记点路由 | `dialogue/SKILL.md` |
| 1 星"已标注"定义 | `MASTERY-STAR-RULES.md` |
| `source: class_point` | 同上 |
| `annotation_ids` / `last_annotation_id` 字段 | 同上 |
| 前置读取 `class-point/points` | `class-interaction/SKILL.md` |

### 移除：区分问题

| 移除项 | 说明 |
| --- | --- |
| 「区分问题」概念 | **整体废弃**，不再作为设计要素 |
| `LESSON-INTERACTION.md` 的易混淆点段 | 整段删除（含 10 组 A vs B 与对应区分问题） |
| FORMAT 中的区分问题要求 | `LESSON-INTERACTION-FORMAT.md` 改为 `LESSON-CONTENT-FORMAT.md`，规则改为"不写易混淆点" |

> 易混淆点**只在 `TMISSION.md` 列名称**（A vs B），不写如何提问。

### 移除：n8n 与前端

| 移除项 | 说明 |
| --- | --- |
| `workflow/` 目录及全部 n8n 构建脚本 | 本仓库不再包含 |
| `classroom-chat/`（课堂聊天页面） | 不做前端 |
| `student-workspace/`（学生页面） | 不做前端 |
| `start-classroom-chat.cmd` | 启动前端用，已无前端 |
| ORCHESTRATOR 的 n8n 节点对照表 | 改为"节点职责总表" |

> 前端相关的数据文件（mastery/dialogue）迁到 `runtime/data/`，因为规则仍需要读写它们。

### 新增：三阶段内容层

| 新增 | 位置 |
| --- | --- |
| 阶段内容层（问题/标准/提示词） | `stages/{recap_discussion,deep_inquiry,class_discussion}/` |
| 四阶段 `host_phase` 枚举 | `DIALOGUE-LOG-FORMAT.md` |
| 编排器字段 | `DIALOGUE-LOG-FORMAT.md` |
| 阶段快照机制 | `MASTERY-STAR-RULES.md` |
| 课程计划配置 | `lesson-data/lesson-plan.json` |
| LangGraph 编排规范 | `orchestrator/ORCHESTRATOR.md` |
| 时钟与切幕参考实现 + 回归测试 | `orchestrator/clock_reference.py` |
| KP 4 个探究字段 | `rules/KNOWLEDGE-BASE.md` |
| 核心难点的 `检验问题` 字段 | `TMISSION-FORMAT.md`（已在 `runtime/TMISSION.md` 补齐 4 条） |

### 改名

| 旧 | 新 | 原因 |
| --- | --- | --- |
| 1 星"已标注" | **1 星"已接触"** | 标注移除后星级需保持连续 |
| `LESSON-INTERACTION.md` | **`LESSON-CONTENT.md`** | 旧名太宽泛，且文件不含交互内容 |
| `lecturing` / `segment_summary` | `guided_learning` / `recap_discussion` | 四阶段模型 |
| `class agent` | `rules` | 去空格 |
| `class-point` | `lesson-data` | 去空格 + 语义更准 |
| `teach test` | `runtime` | 去空格 + 语义更准 |
| `student-workspace/data/` | `runtime/data/` | 无前端后归入运行时 |

---

## 四、待办

- [x] `runtime/TMISSION.md` 补 `检验问题` 字段（每个核心难点）——2026-09-17 已补齐 4 条，并挂上 `KP-xxx` 编号
- [x] 补充"无定时器时如何自动切幕"的方案——2026-09-18 采用**真实时钟**（方案 B），见 `ORCHESTRATOR.md` 第 5 节，参考实现 `clock_reference.py`（12/12 回归通过）
- [x] 按 `ORCHESTRATOR.md` 实现 11 个节点（LangGraph）——2026-09-18 完成，`orchestrator/agent.py`，并用 `run_demo.py` 跑通一整节课（实录见 `demo-run.md`，两次运行结果逐字节一致）
- [x] 会话层接入 `now` 注入——`agent.run_one_turn()` 每轮注入时间戳，图内节点一律不读系统时钟
- [ ] `rules/KNOWLEDGE-BASE.md` 填 4 个探究字段（待老师提供内容）
- [ ] `stages/*/questions.md` 与 `rubric.md` 按需填写（待老师提供内容）
- [ ] 接真实 LLM：配置 `AGENT_LLM_BASE_URL` / `AGENT_LLM_API_KEY` / `AGENT_LLM_MODEL` 即可，代码无需改动
