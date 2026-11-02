# 当前学生端源码对照笔记（2026-10-29）

范围：只读静态核查 `student_agent`，未启动应用、模型或数据库，未修改业务代码。以下结论依据当前工作区；线上部署状态未验证。源码链接定位到本地文件行号。DeepTutor 端由另一份固定提交分析提供。

## 1. 教学控制：图已存在，教学调度仍是确定性规则

**源码事实**：课堂图依次 `evaluate → route → respond`，每次学生提交调用一次 `dialogue_graph.invoke()`；`route()` 直接调用 `progression.advance()`。首轮/加强轮次、首轮后期掌握需确认、讨论题答对才推进由 Python 规则处理。课后另有 `evaluate → advance → respond` 图，完成概念、确认、讨论待办后开放问答。

证据：[课堂图](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:174)、[route](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:97)、[课堂调用](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:519)、[推进规则](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/progression.py:115)、[课后待办类型](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/postclass.py:14)、[课后图](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/postclass.py:131)。

**与方案的区别**：`dialogue-tutoring-design.md` v0.8 提出的“Agent 选择继续/换主题/独立尝试，程序校验执行”仍是设计，没有在上述图中实现。当前模型输出主要是 intent/assessments，未形成显式教学动作合同。

**建议/框架分工**：LangGraph 已能承担分支循环和图运行；需要自己定义 `TeachingDecision`、合法动作、前置条件与学习证据。无需因使用 LangGraph 而固守 8/4 轮教学，也无需替换框架才能实现动态教学。

## 2. 课时上下文与检索：已有发布材料约束，尚无 RAG 主链

**源码事实**：`begin()` 按课时重新取得上下文并校验 user/course/publication/version/selectedLessonId，只接受一个选定课时。`classroom_materials()` 从实际播放器的 visibleText/画布文本和 speech 旁白组织材料，每场景内容截取 6000 字符。提取链把这些场景一次传入模型。当前 Agent 代码未发现 retriever、embedding、vector store 或工具调用循环；它不是检索知识库后动态取材料的 Agent。

证据：[单课时上下文校验](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:366)、[材料组织](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/context.py:8)、[材料截取](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/context.py:28)、[提取入口](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/knowledge.py:199)。

**建议/框架分工**：LangChain 能提供加载/切分/检索接口，但课时与发布版本过滤、PPT 和 HTML 的冲突处理、可引用页码/场景映射必须由业务定义。当前主链尚未直接消费原版 PPT 的完整图文，不能将其说成已完成。材料短时可先做有来源的片段查找，不必默认导入大规模向量检索系统。

## 3. 引用与学习记忆：已有可信基础，缺少稳定教学任务对象

**源码事实**：`validate_candidates()` 校验场景 ID、引用原文、知识点名称与最小证据长度；最终知识点描述保存原文，并以 title+sourceIds 计算 ID。`assessment_history` 保存阶段、轮次、结果、依据和学生原话；概念理解与讨论结果分开。课堂评估仅使用最近 8 条消息，回复使用最近 10 条；课后讨论题上下文通过最近讨论消息保留。

证据：[引用校验](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/knowledge.py:110)、[知识点生成](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/knowledge.py:159)、[评估历史](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/progression.py:139)、[概念与讨论区分](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/progression.py:145)、[近期消息](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:82)、[回复上下文](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:159)、[课后讨论上下文](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/postclass.py:24)。

**建议/框架分工**：保留引用校验和两类结果分离。补充任务 ID、题目正文、帮助程度、尝试 ID、原始回答与判定版本，避免仅靠近期聊天恢复当前问题。LangGraph State/Store 能保存这些对象，但不能自动设计其语义；摘要也不能直接当学生掌握证据。原文匹配只能证明可追溯，不证明语义解释和掌握判断一定正确。

## 4. 结构化输出：有手动校验，可使用 LangChain 减少解析代码

**源码事实**：`_json_object()` 去掉 Markdown 代码块后 `json.loads()`；`evaluate()` 再检查 intent、assessments、合法知识点 ID 和 result 枚举。知识点链在此之上有专门引用验证。当前没有使用 `with_structured_output()`。后端 Pydantic 主要约束请求体，例如文本长度，不是模型完整输出契约。

证据：[JSON 解析](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:67)、[评估字段校验](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:76)、[请求体](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:44)。

**建议/框架分工**：可用 LangChain 结构化输出搭配 Pydantic schema，在模型/网关支持条件下统一格式约束。仍需保留来源、权限、教学动作前置条件等业务验证；输出符合 schema 不代表教学结论可靠。

## 5. 交互与事件：普通 HTTP 完整响应，尚无生成流

**源码事实**：前端 `api()` 对 fetch 结果执行 `response.json()`，消息提交等待后端整次 graph.invoke 完成。知识点准备状态每两秒轮询。当前课堂主链没有 SSE/WebSocket 消息流、工具事件面板或可重放事件序列。

证据：[前端接口读取](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/frontend/src/components/StudentApp.js:8)、[准备轮询](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/frontend/src/components/StudentApp.js:191)、[消息提交](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/frontend/src/components/StudentApp.js:302)、[后端整轮调用](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:535)。

**建议/框架分工**：LangGraph/LangChain 提供 token、节点状态等流式基础；SSE/WebSocket、事件类型、序号、持久化、重连补发和前端呈现仍需应用实现。建议先显示“核对回答/查阅材料/生成回复”等必要进度，不把内部推理直接当学习内容展示。

## 6. 恢复与事务：业务快照已实现，不等于图节点恢复

**源码事实**：两张图都直接 `compile()`，未配置 checkpointer。`persistence.save()` 写消息、掌握状态和 `agent_state` 快照；`restore()` 读取最近快照。默认 fresh_session_mode=1，数据库仍写，但恢复优先来自当前浏览器 localStorage 中的 HMAC 签名完整快照。服务缓存缺失且 fresh 模式开启时，`get_session()` 不读数据库恢复。完成反馈、最终快照和结束状态在一个事务内提交；此前 session/message/mastery 是分别提交。

证据：[课堂 compile](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:182)、[课后 compile](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/postclass.py:139)、[fresh 默认值](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/persistence.py:11)、[签名快照](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:53)、[缓存恢复](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:128)、[快照写入](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/persistence.py:55)、[完成事务](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/persistence.py:82)、[数据库各函数提交](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/database.py:21)。

**建议/框架分工**：LangGraph 持久 checkpointer 可恢复图状态；课程学习事实、消息与成绩的一致性仍需自己的事务/幂等策略。先定义业务数据库与图 checkpoint 各自负责哪些事实，避免两套权威状态。不能仅加 MemorySaver 就声称跨设备和重启恢复完整。

## 7. 并发与后台准备：单进程防重已有，多实例协调和请求幂等尚不足

**源码事实**：会话存在进程内 `sessions` 字典，每会话 threading.Lock；知识点准备由 FastAPI BackgroundTasks 执行，`preparing` 集合仅在本进程防重。准备模型调用不持有会话锁，防止阻塞视频状态；但课堂/课后消息在持有会话锁时同步调用模型。MessageRequest 只有 text，没有 attemptId/请求幂等键；成功后客户端因网络中断重发可能再次计入一轮。pending 准备通过读会话等路径重新调度，不是独立持久任务队列。

证据：[进程缓存与锁](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:35)、[消息请求体](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:44)、[准备执行](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:223)、[后台调度](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:256)、[读会话再调度](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:358)、[持锁模型调用](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:519)、[课后持锁调用](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:592)。

**建议/框架分工**：checkpoint 不替代任务队列、跨实例协调或业务幂等。扩展前定义 turnId/attemptId、状态版本、一次提交的原子性及恢复策略。异步图调用可以改善资源使用，但不自动解决并发写冲突。

## 8. 成本与可观测性：有错误和准备耗时日志，缺少统一调用统计

**源码事实**：模型接口配置 timeout=45、max_retries=1；`_completion()` 立即把 AIMessage 转为 content 字符串，没有向上返回 usage_metadata 等数据。知识准备记录 request_id、耗时、接受/拒绝条数；课堂/课后主要记录失败异常。当前课堂普通教学轮次包含评估与回复两个逻辑模型调用（重试另计）；总结分支可用专门的最终讨论反馈调用替代普通教学回复，不能把所有路径都概括为固定次数。当前 Agent/后端主链未发现统一 token、费用、节点耗时账本或预算约束。

证据：[模型超时重试](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:50)、[丢弃模型元数据](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:62)、[评估](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:76)、[最终讨论反馈](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:101)、[回复生成](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/agent/graph.py:127)、[准备日志](E:/LMS系统参考/项目/agentic-class-pilot-running/student_agent/backend/main.py:223)。

**建议/框架分工**：可用 LangChain 的模型响应元数据、callbacks/middleware 和图事件采集调用事实；成本定价、模型供应商实际 usage、每课/每生预算以及教学质量评估仍要自己组织。LangSmith 是可选配套产品，不能与安装 LangGraph 等同。

## 借鉴时应保留的本地设计

- 平台课程、发布版本与课时的隔离校验。
- 原文校验后再作为教学内容，保留 material/sourceIds。
- 概念理解与应用讨论结果分开。
- 依据本次真实评估记录生成反馈，不用历史最高掌握度替代当前表现。
- 课后补完与课堂原始反馈分开保存。
- 模型失效时不提交本轮新计数，先持久化成功再更新会话。

以上只是本地源码静态事实和改造建议，不证明真实教学效果，不将设计稿当已实现功能。本次未执行测试，因为没有修改实现。

