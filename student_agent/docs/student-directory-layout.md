# 学生端目录与依赖说明

日期：2026-11-02。对应 P1–P5 已实现的 Module，完成源码物理归位和导入修正。本次不新增教学功能、不变更流程或数据库结构。现行目录以本文和 [README](../README.md) 为准；[模块架构设计](student-module-architecture-design.md)中的现状分析和历史实施记录保留当时背景。

## 1. 目录与职责

```text
student_agent/
├─ backend/
│  ├─ __init__.py
│  ├─ main.py                      HTTP、应用生命周期和静态资源入口
│  ├─ contracts.py                 共享异常、稳定身份算法和流程名称
│  ├─ requirements.txt
│  ├─ session/
│  │  ├─ service.py                进入、恢复、换版、课堂/课后用例与统一提交
│  │  └─ command_runtime.py        命令执行、租约心跳、恢复及进度同步调度
│  ├─ teaching/
│  │  ├─ service.py                会话调用的教学 Interface，选择实际流程 Adapter
│  │  ├─ graph.py                  原课堂 LangGraph
│  │  ├─ postclass.py              原课后 LangGraph
│  │  ├─ dynamic_teaching.py       P4 受限动态执行器
│  │  ├─ progression.py            原课堂纯状态推进
│  │  ├─ postclass_state.py        纯课后状态投影、待办与评估应用
│  │  ├─ dynamic_state.py          固定动态规则、状态读取与决策异常
│  │  └─ prompts.py                课堂/课后教学提示词
│  ├─ evidence/
│  │  ├─ records.py                消息/任务身份关联、观察与帮助验证
│  │  └─ feedback.py               legacy 与动态反馈的纯计算
│  ├─ content/
│  │  ├─ context.py                课堂场景和旁白整理
│  │  ├─ knowledge.py              内容提取与来源校验
│  │  ├─ lesson_content.py         不可变版本内容的纯定义、构建、验证与绑定
│  │  └─ prompts.py                内容提取提示词
│  ├─ infrastructure/
│  │  ├─ database.py               PostgreSQL 连接和基础记录写入
│  │  ├─ persistence.py            权威快照、统一事务、恢复与清理 Adapter
│  │  ├─ commands.py               命令日志、CAS、租约和完成事务 Adapter
│  │  ├─ content_store.py          内容版本读写与固定版本 hydration
│  │  ├─ published_knowledge.py    共享内容准备任务、SQL 租约及 worker
│  │  ├─ model.py                 模型调用 Adapter
│  │  └─ platform_access.py       平台上下文、授权和学情同步 Adapter
│  └─ tests/                      功能、事务、并发、恢复与目录依赖回归
├─ frontend/                      P5 页面与统一学习交互，不改其目录契约
├─ apps/                          现有部署 launcher
├─ scripts/                       部署脚本
└─ docs/
   └─ archive/                    从原 agent 目录迁出的历史实现说明
```

原 `agent/` 目录已移除，业务源码全部进入新的职责包，旧生成字节码也已清理。所有项目导入都指向新路径，不在旧目录保留 Python 转发层。

### 学生端新增文档与验证记录

本次及后续学生端知识点教学文档统一归属学生端目录，不再新增到仓库根目录的 `docs`：

- `student_agent/docs/knowledge-teaching/`：教学方案、实施说明及过程记录。
- `student_agent/docs/knowledge-extraction/`：知识点提取验证及其索引。
- `student_agent/evidence/`：真实模型、HTTP流程的报告、脚本和原始输出；含失败记录。

`student_agent/backend/evidence/` 仍是运行时学习证据模块，与上述测试产物目录用途不同。早期的 `student_agent/.personal-dev/docs/` 归档保留，当前教学入口以学生端 README 为准。

## 2. 如何放置后续代码

| 要做的变更 | 放置位置 | 不应承担的职责 |
|---|---|---|
| 新增学习操作、协调身份/状态/事务 | session | 不写新教学判断或生成提示词 |
| 新增教学动作、合法转移或生成策略 | teaching | 不自行写库或改变平台身份 |
| 学习原话、帮助、证据校验及反馈 | evidence | 不调度下一题，不调模型、不写 SQL |
| 来源整理、提取和课时版本定义 | content | 不混入学生表现和会话记录 |
| PostgreSQL、模型、平台 HTTP、准备 worker | infrastructure | 不拥有教学推进规则 |
| 跨 Module 的稳定身份或错误契约 | contracts.py | 不导入业务包，不放可变状态或外部调用 |

`infrastructure` 内有两类 Adapter：model/database/platform_access 是外部访问叶节点；persistence/commands/content_store/准备 worker 是用到内容及证据定义的具体 Adapter。这里并不承诺“所有包只能单向导入 infrastructure”这种与现有实现不符的层级。实际规则是计算侧和执行侧分别限制其依赖，避免为了目录整齐再引入一层无实际差异的转发。

## 3. 已落实的依赖规则

- `backend.main` 负责 HTTP、请求模型、异常转换、生命周期和静态文件。业务模块不导入 main，不依赖 FastAPI。
- session 通过教学 Interface 和基础设施 Adapter 编排用例。会话状态、提交和模型执行规则继续沿用 P1/P2 的责任分工。
- 教学执行器和内容提取可使用 `infrastructure.model`；SQL、平台 HTTP 和持久化不进入教学节点或纯内容定义。
- evidence 的完整依赖闭包只包含纯内容定义、共享契约、纯课堂/课后/动态状态及纯反馈，不再为了生成稳定身份反向加载动态执行器。
- content.lesson_content 不导入数据库；store/find/hydrate 全部移动到 infrastructure.content_store，继续接受调用者连接，保持同一事务。
- 内容提取提示词归 content.prompts，教学提示词归 teaching.prompts；已有六项可字面求值的提示词/字典与原跟踪源码逐项比较一致。提取器版本、模型输入和整理结果缓存不会因移动文件而变化。
- 共享 identity 仍使用原 UUID5 与原 JSON 编码，不改变已有任务、消息或活动身份。共享流程名称和状态异常保持相同语义。
- eager 模块导入图无环。session.service 与 command_runtime 仍保留原会话 Module 内部用于缓存投影/错误映射的延迟调用关系，未在此次整理中重写缓存协议；没有新增跨职责的延迟环。

结构验证见 [test_module_layout.py](../backend/tests/test_module_layout.py)。它验证旧导入及子进程片段已迁移、纯模块的完整依赖闭包、eager 图无环及 HTTP 依赖隔离，并通过独立进程检查真实入口。

## 4. 关键迁移映射

| 原位置 | 当前位置 |
|---|---|
| backend/learning_session.py | [session/service.py](../backend/session/service.py) |
| backend/command_runtime.py | [session/command_runtime.py](../backend/session/command_runtime.py) |
| backend/teaching.py | [teaching/service.py](../backend/teaching/service.py) |
| backend/platform_access.py | [infrastructure/platform_access.py](../backend/infrastructure/platform_access.py) |
| backend/errors.py | [contracts.py](../backend/contracts.py) |
| agent/graph.py、progression.py、postclass.py | teaching 下的同名文件；纯课后函数另归 postclass_state.py |
| agent/dynamic_teaching.py | teaching/dynamic_teaching.py；纯规则/状态归 dynamic_state.py；反馈归 evidence/feedback.py |
| agent/learning_records.py | [evidence/records.py](../backend/evidence/records.py)；身份算法归 contracts.py |
| agent/feedback.py | [evidence/feedback.py](../backend/evidence/feedback.py) |
| agent/context.py、knowledge.py | content 下的同名文件 |
| agent/lesson_content.py | [content/lesson_content.py](../backend/content/lesson_content.py)；存储归 content_store.py |
| agent/prompts.py | teaching/prompts.py 与 content/prompts.py，提示词原文保持不变 |
| agent/commands.py、persistence.py、database.py、model.py、published_knowledge.py | infrastructure 下的同名文件 |
| agent/学生端Agent实现详解.md | [历史实现说明](archive/student-agent-implementation-baseline.md) |

旧内部 Python 导入路径不提供转发兼容层；项目源码、测试、子进程恢复脚本与文档引用均直接迁移。HTTP Interface 和已有部署入口继续兼容。历史文档中的旧目录树是当时分析快照，代码链接已更新，不应将历史树当作现行结构。

## 5. 启动、存储与发布兼容

以下位置保持不变：

- `backend.main:app`、`apps.server:app`、`python apps/start.py` 及其参数。
- `backend/requirements.txt`、`backend/tests`、`frontend/out`、本地启动与部署脚本。
- 所有 HTTP 路由、SessionView、命令载荷、快照字段、contentRef、flowVersion、policyVersion、SQL 及迁移顺序。

因此工作流无需改变安装、构建、测试或启动命令。独立进程使用隔离假配置验证冷导入、三个入口引用同一 app、健康检查、OpenAPI、静态输出位置和 CLI help；测试不读取本机平台凭据，不启动模型或正式数据库连接。

本次没有新增迁移。发布仍需要应用现有 cmd11/rec12，保留 P4/P5 对动态会话的兼容执行能力，并按已有流程排空写入；没有在本次任务中部署、迁移正式库或启用试点。

## 6. 验证记录

最终后端完整 **177 项通过**（126 离线、51 真实 PostgreSQL，97.33 秒），包含原 173 项及新增四项目录/依赖/冷启动检查。

前端 **42 项单测**、**17 项浏览器回归**通过，生产构建成功；前端没有变更业务源码。Python 编译、26 份 Markdown 本地链接/围栏及本次改动差异检查通过。专用随机测试库剩余 0，校验数据目录归属后已停止测试集群。Next 自动生成的 AGENTS.md 已清理。本次验证继续使用隔离模型/平台替身和专用回环 PostgreSQL，覆盖原教学轮次、课堂/课后、版本绑定、幂等、并发、失败重试、进程崩溃恢复、回看和暂停/继续。真实教学质量仍以 P4 抽样质量门槛为准。
