# 课时知识点提取

本目录集中保存本次 `memory / concept / design` 结构化知识点提取改造的设计、历史调研、实施记录和验证产物。工作树为 `typed-knowledge-extraction`，分支为 `lzm2`；未部署。

结构化知识点的核心协议、提取、保存和字段传递已基本完成，完成范围与限制以实施记录为准。后续学生端教学使用独立维护在 [结构化知识点的教学使用方案](../knowledge-teaching/plan.md)，不纳入本目录的提取设计或待实施范围。

## 阅读入口

| 分类 | 文档 | 用途 |
| --- | --- | --- |
| 设计 | [当前方案](design/plan.md) | 数据协议、反馈修正闭环、职责边界与验收标准 |
| 实施 | [代码改动与测试](implementation/changes-and-tests.md) | 已实现行为、兼容处理、测试结果和限制 |
| 实测 | [2026-11-05 真实课时与模型试验](validation/2026-11-05-live-model/README.md) | 三种知识点样例、真实反馈修正和质量观察 |
| 实测 | [2026-11-10 要求拆分提示词验证](validation/2026-11-10-requirement-splitting/README.md) | 公开提取入口前后对照；真实课时仍未拆开，保留失败 |
| 实测数据 | [固定格式知识点 JSON](validation/2026-11-05-live-model/knowledge-points.json) | 直接查看真实课时的 11 项核心输出 |
| 历史调研 | [替代方案比较](research/alternative-approaches.md) | 前期选项及一手资料，不作为当前实施要求 |
| 工作记录 | [实施计划](records/task-plan.md)、[关键发现](records/findings.md)、[实施与测试日志](records/progress.md) | 本次工作的过程记录，不混入仓库已有的其他项目历史 |

## 目录约定

```text
knowledge-extraction/
├── README.md
├── design/
│   └── plan.md
├── research/
│   └── alternative-approaches.md
├── implementation/
│   └── changes-and-tests.md
├── validation/
│   └── 2026-11-05-live-model/
│       ├── README.md
│       ├── knowledge-points.json
│       ├── natural.json
│       ├── injected-repair.json
│       └── initial-provider-error.json
└── records/
    ├── task-plan.md
    ├── findings.md
    └── progress.md
```

后续设计修订继续更新 `design/plan.md`；实现及测试说明更新 `implementation/changes-and-tests.md`。新的实测按 `validation/YYYY-MM-DD-试验主题/` 单独保存，并在各次试验的 README 中说明条件、结果、原始文件和限制。

自然提取、故障注入和初始接口错误分别保存，避免把人为注入故障当作模型自然失败。密钥、原始配置、本机临时输入快照和运行脚本不进入本目录。

## 整理记录

- 2026-11-05：将本次方案、实施记录和实测产物统一收拢到本目录，补入历史调研副本，更新相对链接。
- 将本次追加的计划、发现和日志迁入 `records/`；仓库根目录原有历史记录保持原内容。本次整理未改动业务代码或实测 JSON 内容。
