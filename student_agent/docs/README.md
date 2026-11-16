# 学生端文档目录

整理日期：2026-11-16。现行说明以本目录的架构和指南为入口；日期化记录只证明当时的实施与验证范围。

| 文件夹 | 内容与入口 |
|---|---|
| `guides/` | [学生学习流程](guides/student-workflow.md)、[教学阶段](guides/teaching-stages.md)、[本地开发](guides/local-development.md) |
| `architecture/` | [当前架构](architecture/student-architecture-current.md)、[目录与依赖](architecture/student-directory-layout.md) |
| `knowledge-extraction/` | [知识点提取及验证索引](knowledge-extraction/README.md) |
| `knowledge-teaching/` | [三类型教学设计、实施和验证](knowledge-teaching/README.md)；早期记录按日期阅读 |
| `releases/` | [2026-11-13 教学发布说明](releases/2026-11-13-typed-teaching.md)、[提取输出预算修复](releases/2026-11-13-extraction-output-budget.md) |
| `research/` | 外部产品、框架和源码调研，保留调研时的结论，不代表当前实现 |
| `simulation-experiment/` | [批量模拟实验方案](simulation-experiment/plan.md)、画像、评估规范与配置；方案不等于已完成实验 |
| `archive/` | [历史归档索引](archive/README.md)：旧方案、P1–P5 实施、旧实现基线 |

[学生端 evidence](../evidence/) 保存真实模型、HTTP 与恢复验证的报告和原始产物；运行时代码 `backend/evidence/` 则负责学习证据，两者用途不同。

本机个人说明、任务和诊断记录按 [个人文档入口](../.personal-dev/README.md) 管理，不入库。发布构建快照和原始实验数据保留原样，不随文档分类搬迁。

维护时：现行行为变化须同步架构与指南；历史验收数字不改写成当前结果；新方案明确状态；验证报告与原始数据一起保留。教师端及平台共享文档不在本次整理范围。

## 当前流程与提示词

- [流程图、各环节提示词全文及源码对应（2026-11-16）](guides/student-flow-prompts-20261116.md)
