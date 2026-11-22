# 学生端知识点提取

按 2026-11-22 本地源码整理。

## 现行提取协议

- 输入为当前已发布课时的场景画面文字和讲解旁白。程序按场景顺序整理，每个场景正文最多 6000 字符。模型输入为 `{"materials": [...]}`，课程、课时标识用于生成带作用域的稳定知识点 ID。 [材料整理](../../backend/content/context.py) · [提取执行](../../backend/content/knowledge.py)
- 模型通过 `submit_knowledge_points` 提交 3–8 项，精确去重后仍须至少 3 个不同知识点。每项包含 `title`、`type`、`details`。 [提示词全文](../../backend/content/prompts.py) · [工具参数和校验](../../backend/content/knowledge_schema.py)

| 类型 | `details` 字段 |
|---|---|
| `memory` | `statement`、`requiredElements` |
| `concept` | `explanation`、`understandingPoints` |
| `design` | `capability`、`constraints`、`successCriteria` |

- 提示词要求只选课件实际讲授的内容。程序校验工具名、参数结构和数量，规范化文本，合并完全相同的知识点，并从结构字段派生供兼容流程使用的 `content` 和 `description`。来源清单是课时级材料记录，每个知识点的语义贴合度仍依赖模型。 [提取执行](../../backend/content/knowledge.py) · [内容包](../../backend/content/lesson_content.py)
- 格式错误或缺少工具提交时，在同一次 Agent 执行内要求重提完整列表。每次执行最多 3 次模型调用，总预算 180 秒，单次最多 120 秒，配置的输出上限为 32768 token。没有可用材料或提取失败时返回准备错误。3–8 项约束只用于新提取，已有内容包使用独立的存量 schema。 [提取执行](../../backend/content/knowledge.py) · [存量与提取 schema](../../backend/content/knowledge_schema.py)

## 准备任务与内容版本

1. 平台入队接口按 `courseId / lessonId / videoRevision` 去重。已有发布课时也可在读取学习上下文时补建任务。 [入队接口](../../backend/internal_platform.py) · [平台课时上下文](../../../platform/backend/app/api/routes/student_bridge.py)
2. Worker 复用符合课时、视频版本、编译器和来源清单的内容包，必要时领取任务并调用 `prepare_content`。任务租约、失败诊断和结果写入由 worker 管理。已领取任务的编译器标识在本次执行中固定，成功写入准备状态和不可变内容包共用数据库事务。 [准备编排](../../backend/infrastructure/published_knowledge.py) · [内容准备](../../backend/content/preparation.py)
3. 编译器标识随提取版本、提示词或工具 schema 变化。已有内容版本可与新版本并存。新会话通常在视频准备阶段读取就绪结果并绑定 `contentRef`。恢复已绑定会话时按内容 ID 读取原包，并校验课时、来源版本、引用及教学点。 [内容存储](../../backend/infrastructure/content_store.py) · [会话绑定](../../backend/session/content_binding.py)
4. 正式课堂可在页面重试失败任务。Worker 对提取层返回的 `KnowledgePreparationError` 记录需手动重试，其他任务异常可按退避时间重新领取。 [重试与失败状态](../../backend/infrastructure/published_knowledge.py)

## 历史验证

- [要求拆分与去重验证](validation/2026-11-10-requirement-splitting/README.md)
- [下游教学方案与验证入口](../knowledge-teaching/README.md)
- [复合项帮助修复及真实模型证据](../../evidence/compound-help-fix/REPORT.md)
