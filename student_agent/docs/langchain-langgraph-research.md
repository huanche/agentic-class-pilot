# DeepTutor、LangChain 与 LangGraph 选型核查

核查日期：2026-10-29。依据官方在线文档与 DeepTutor upstream main；main 会变化，实施前应固定 tag 或 commit。以下“建议”是针对教学平台的工程判断。

## 三者的层次

| 项目 | 提供的主要能力 | 不替你决定的事项 |
|---|---|---|
| DeepTutor | 已成形的教学应用与领域设计，包括聊天、引导学习、解题、练习、研究、可视化、知识库及记忆等 | 你的学校、课程、成绩、权限与平台业务规则 |
| LangChain | 模型与工具集成、可配置 agent loop、结构化输出、RAG 组件及中间件 | 教学策略、掌握标准与完整 LMS |
| LangGraph | 状态图、分支循环、持久化、中断恢复与流式执行等编排基础设施 | 节点内的教学逻辑与产品界面 |

DeepTutor 当前源码文档描述两层插件：一次性 Tools、多阶段 Capabilities；由 ChatOrchestrator 统一调度，StreamBus 分发事件。它体现完整应用如何组织领域能力，不等同于通用工作流库。参考：[DeepTutor 架构文档](https://github.com/HKUDS/DeepTutor/blob/main/AGENTS.md)。

LangChain 当前 `create_agent` 提供模型、工具、提示词、中间件组成的 agent harness；LangChain agents 运行于 LangGraph。LangGraph 可以独立使用，不要求采用 LangChain。因此这不是三选一。参考：[LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)、[LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)。

## 框架具体省下什么工作

- **模型与工具接入、agent loop**：统一常见模型接口，让模型选工具、观察结果、继续生成，适合开放问答。[LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)
- **结构化输出**：按 schema 返回并校验 JSON/Pydantic 等数据，适合题目、评估记录；格式正确仍不代表答案或评分正确。[Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
- **RAG 组件**：文档加载、切分、embedding、向量库、retriever。检索策略、教材权限、证据引用与教学质量仍需应用设计。[Retrieval](https://docs.langchain.com/oss/python/deepagents/retrieval)
- **中间件**：为调用过程增加日志、动态提示词/工具选择、重试、fallback、限流与终止规则。[Middleware](https://docs.langchain.com/oss/python/langchain/middleware/overview)
- **状态与恢复**：checkpointer 保存单线程图状态；store 保存跨线程应用数据。内存 checkpointer 重启即丢失，生产恢复需持久后端。它们不自动构成成绩库或学情模型。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- **等待学生输入**：`interrupt` 暂停，之后以同一 `thread_id` 和恢复值继续；恢复时该节点从头执行，中断前副作用需幂等或单独设计。[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- **流式输出**：支持模型消息、节点状态更新、自定义进度等事件；前端 SSE/WebSocket 接入仍需实现。[Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)

## 当前项目的落点与建议

本地已有架构说明 `student-architecture-current.md` 记录课堂和课后两个 LangGraph，并区分确定性教学推进、模型评估/生成与业务持久化。该说明不是本次重新逐行验证的代码审计。

建议保留现有平台/课程/学情业务边界，参考 DeepTutor 的学习交互、教学能力与证据呈现；需要严格控制的教学流程继续使用 LangGraph。模型适配、结构化输出或检索组件可按实际收益引入 LangChain，无须为了“用了成熟框架”将整套业务改为通用 agent loop。

例如：检索课程材料 → 提出诊断题 → 等学生作答 → 评估证据 → 未掌握则提示/补练、已掌握则进入下一知识点。转移条件、尝试次数与完成标准由程序规则控制；LLM 负责题目生成、语义评估与解释。

只有目标接近独立 DeepTutor 产品、且愿意接受其业务边界和升级成本时，直接 fork 并二次开发才可能更省时。若只是普通材料问答，单次模型调用加检索即可，无须先建复杂状态图。上述为场景建议，而非框架官方结论。
