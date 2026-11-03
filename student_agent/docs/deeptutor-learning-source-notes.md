# DeepTutor 教学业务源码核查笔记

核查日期：2026-10-29。固定参考版本：[`1ea7df155447f4caf0e3abc86b3ff5395479cd4a`](https://github.com/HKUDS/DeepTutor/tree/1ea7df155447f4caf0e3abc86b3ff5395479cd4a)。只做静态阅读，未运行 DeepTutor、模型或学习流程；未修改业务代码。本笔记聚焦教学领域，供主架构对照报告使用。

## 1. 实际代码位置与运行关系

当前路径是 `deeptutor/capabilities/mastery/`，能力对外名称仍为 mastery_path，不能按照旧版目录或早期双循环图理解当前代码。

- `capabilities/mastery/loop.py::MasteryLoopCapability`：给共享 Agent 循环增加教学专用提示、工具绑定、状态预读和收尾约束；不是另写一个完全独立的教学运行引擎。
- `capabilities/mastery/tools.py`：模型可请求的教学动作，如 `MasteryStatusTool`、`MasteryQuizTool`、`MasteryAssessTool`、`MasteryPrepareLessonTool`、`MasteryReviseTool`。
- `learning/models.py`：学习目标、题目契约、作答、理解证据、待办交互及持久状态。
- `learning/service.py::LearningService`：注册题目、记录作答、评分落库、修订目标等业务操作。
- `learning/policy.py`：无模型、无 I/O 的规则计算，决定目标是否通过及下一目标。
- `learning/lesson_evidence.py` 与 `semantic_assessment.py`：来源准备、来源与目标版本校验、题目及答案依据绑定、语义判定。

入口参见 [`MasteryLoopCapability`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/loop.py#L43)、[`LearningService`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/service.py#L328)、[`policy.py`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/policy.py#L1)。

## 2. 六项值得借鉴的具体设计

### A. 让当前业务状态成为每轮的权威输入

**源码事实**：`MasteryLoopCapability.pre_loop()` 在第一轮模型调用前，直接调用同一 `MasteryStatusTool` 读取当前路径状态。绑定在读取期间改变则丢弃结果；本轮快照不会当作跨轮缓存。卡片题已评分时，`pre_loop_seed()` 把已发生的评分结果交给导师；短答案如“A”不会被当作检索问题执行知识库搜索。

来源：[`loop.py:415`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/loop.py#L415)、[`pre_loop_seed/skip_kb_seed`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/loop.py#L462)。

**对本项目的建议**：每轮传入当前课时/任务、学生原话、已提供帮助、待验证事项及状态版本；避免让导师从历史聊天猜当前任务。现有 `DialogueState` 已有基础，可扩展而无须换引擎。LangGraph State/节点和 LangChain 消息组织能实现机制；哪些状态权威、何时刷新仍是本项目业务设计。

### B. 教学动作在执行时校验，提示词不承担授权

**源码事实**：`mode.py::TOOL_MODES` 定义 outline/study/review 对工具的约束；`tools.py::_wrong_mode_result()` 每次执行时检查当前模式。原因是一次 turn 内可以切模式，而工具 schema 通常在 turn 开始组装，单靠当初是否挂载工具不足以约束后续操作。

来源：[`mode.py:65`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/mode.py#L65)、[`_wrong_mode_result`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/tools.py#L625)。

**对本项目的建议**：把“继续当前主题、换主题、开始独立尝试、请求总结”等建成受限动作。Agent 选动作，程序核验当前状态、任务身份和前置条件再执行，符合现有 v0.8 设计。LangChain 工具/结构化输出及 LangGraph 条件分支可承载；合法动作表、校验规则和平台权限不能由框架生成。

**不能照搬的兼容行为**：`enforced_mode()` 对未记录/不认识的模式返回 None，`tool_is_allowed()` 为兼容旧会话和 CLI/SDK 默认允许。课程平台需要显式上下文与权限，不应将这一兼容逻辑当作严格的访问控制。

### C. 记录“独立表现”和“得到帮助后表现”的差别

**源码事实**：`QuizAttempt.independent`、`LearningEvidence.hints_used/learner_answer/feedback/session_id/turn_id` 记录具体证据。`LearningService._apply_grade()` 根据帮助暴露决定独立性；受助答对会降低该次证据 quality 的上限。`policy.learning_stage()` 区分未覆盖、已练但未证明、受助练习、独立证明，公开展示不把这些混成“已掌握”。

来源：[`QuizAttempt`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/models.py#L124)、[`LearningEvidence`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/models.py#L171)、[`_apply_grade`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/service.py#L574)、[`learning_stage`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/policy.py#L110)。

**对本项目的建议**：优先保留题目/任务 ID、学生原话、帮助程度、来源、判定依据和评估版本。现有 `progression.py` 保存 assessment_history，`feedback.py` 分开概念与讨论结果，值得保留；目前未形成同等明确的题目与帮助暴露契约。框架可以保存这些字段，但不会替我们定义“独立表现”的含义。DeepTutor 的 0.6 等数值只是该项目策略，不是可直接复用的教育测量结论。

### D. 把问题变为稳定的服务端业务对象，而非一段聊天文字

**源码事实**：`PendingQuestion` 保存题干、选项、expected_answer、explanation、出处快照和帮助状态；`public_pending_question()` 的公开投影不包含答案与参考解释。`MasteryInteraction` 有 registered/awaiting_input/answered/graded/abandoned 生命周期。`LearningService.register_question()` 重试时保留现有问题；`grade_interaction()` 在事务中检查问题身份，已评分则重放结果，不追加第二次尝试；评分期间目标或问题改变会拒绝提交。

来源：[`PendingQuestion/InteractionStatus`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/models.py#L258)、[`public_pending_question`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/pending.py#L249)、[`register_question`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/service.py#L815)、[`grade_interaction`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/service.py#L1146)。

**对本项目的建议**：将当前讨论题从最近消息中独立出来，绑定 taskId/attemptId、课时版本及受助状态。这样刷新、超时重发或旧页面提交不会重复评分或答错题。LangGraph interrupt/checkpointer 能恢复执行位置；题目答案保密、业务事务和幂等记分仍需自己的数据库实现。没有必要因此迁入 DeepTutor 的整套交互存储。

### E. 来源不是“检索到就算通过”，缓存不是“ready 就永远有效”

**源码事实**：`lesson_evidence.py::cached_lesson()` 检查模型/准备版本和课程意图指纹，再调用 `validate_evidence()` 核验目标、来源范围/索引指纹、授权及真实页引用。partial evidence 可支持覆盖范围内的教学，但不能自动支持任意测评。`semantic_assessment.bind_questions()` 为准确的题干和答案/量规检查来源；`validate_question()` 检查契约指纹，防止校验后修改题目或答案。模型判断是否“支持”仍不是科学事实的独立证明，源码对此有明确说明。

来源：[`cached_lesson`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/lesson_evidence.py#L165)、[`validate_evidence`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/lesson_evidence.py#L351)、[`bind_questions`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/semantic_assessment.py#L217)、[`validate_question`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/semantic_assessment.py#L333)。

**对本项目的建议**：在现有原文校验基础上保留资源 ID、发布版本、PPT 页/HTML 场景及内容 hash；资料变化时重新准备本课材料，历史证据继续关联旧版本。PPT+HTML 是本项目稳定输入，不能直接采用 DeepTutor 面向 PDF 页、知识库索引的整个准备管线。LangChain loader/retriever 可替换通用读入与检索；范围、引用身份和失效规则是应用责任。

### F. 材料视口成为上下文，导师能知道“学生正在看哪里”

**源码事实**：`ReadingCapability.pre_loop_seed()` 从 viewport 获取当前 locator、媒体时间和选中文本；确认权限后注入上下文，必要时标记当前页原图/图示。`pre_loop()` 用局部搜索定位当前资料相关片段，失败时不伪造结果。选中文本明确作为不可信引用处理。

来源：[`ReadingCapability.pre_loop_seed`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/reading/capability.py#L354)、[`pre_loop`](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/reading/capability.py#L403)。

**对本项目的建议**：后续可让学生从当前 PPT 页/HTML 场景发起问题，并带上定位信息。保持整段播放这一既有约束；这一借鉴并不要求改成分段授课。LangGraph 可传状态、LangChain 可检索，但 iframe/postMessage、来源定位和前端引用交互需要自己接入。当前播放器适配能力不能假定已经支持任意跳转或精准时间定位。

## 3. 不应直接移植的策略

1. `policy.py::QUANTITATIVE_GATE` 的 0.9、按知识类型的门槛、`mastery.py::compute_mastery()` 的最近五次加权和一两次作答封顶，是 DeepTutor 的产品策略。可以借鉴“策略单独集中、可替换”的组织方式，不宜据此声称能准确测量我们学生掌握度。[policy](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/policy.py#L33)、[compute_mastery](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/mastery.py#L26)。
2. `policy.is_mastered()` 把明确的学生自报覆盖也作为可前进依据，并用来源标记区分。这适合自主学习导航，不能直接作为本平台正式课程完成/掌握证明。[mastery_source/is_mastered](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/policy.py#L139)。
3. `grading.py::grade_answer()` 存在短答案字符串相似度与开放题关键词规则；新语义评估链路又使用模型及来源契约。不能看到某个 fallback 函数就概括“DeepTutor 已可靠解决语义评分”，也不能把字符串相似度拿来判概念理解。[grade_answer](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/learning/grading.py#L13)。
4. `MasteryReviseTool` 保持目标不变、重写知识点使用新 ID 以隔离旧证据，这个原则可借鉴；允许学习者与 Agent 重建课程大纲不适合直接套到教师已发布的正式课堂。可在本课允许内容内部调整顺序，而不修改教师发布内容。[MasteryReviseTool](https://github.com/HKUDS/DeepTutor/blob/1ea7df155447f4caf0e3abc86b3ff5395479cd4a/deeptutor/capabilities/mastery/tools.py#L2754)。

## 4. 优先顺序建议

优先：稳定题目/任务与作答证据对象 → 受限动作校验 → 来源与状态版本绑定 → 每轮当前状态简报。其次：按页/场景定位的材料问答、增量进度与引用展示。跨课程个性化、间隔复习和自建课程大纲待本课辅导有效性得到验证后再考虑。

这些建议可在现有 FastAPI + LangGraph + PostgreSQL 内逐步实现。借鉴的是教学领域对象和执行约束；共享 Agent 循环、结构化输出、检索组件、图状态、暂停恢复和流式事件无需再照着 DeepTutor 自建一套。
