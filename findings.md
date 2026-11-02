# 学生端现状核查

## 2026-10-27 模拟实验设计核查

- 当前 API 可执行 start→begin→轮询准备→discussion→message→end→feedback，课后另有 start/message；不需要为讨论稿新增业务接口。
- state() 返回 messages、agentStage、learningProgress、feedback；默认 browserSnapshot 内包含完整 dialogue，但原始快照含上下文，不能直接交给模拟学生或外部评估模型。
- 实际每轮学生消息仍先保存旧阶段，助手回复保存推进后的阶段，取证须分别保存请求前后状态；不能按回复阶段归属学生评估。
- 课堂深入讨论只有答对才推进，课后补完也无固定轮数上限；这属于待实验复核的风险，不代表已观察到线上故障。
- /end 是明确 API，学生文字说“结束”不等于调用退出；浏览器退出按钮存在，不能把未自动跳过一概当作缺陷。
- browser-restore 在同进程会复用已有 sid；验证重启恢复需真正隔离重启或清除该测试进程内存，不能伪称普通 restore 调用测试了服务重启。
- 现有 demo 输入只是演示摘要，不能替代真实课程；主实验需隔离平台/数据库及已发布、可回溯的真实课时内容。
- 现有规划文件和 student_agent/docs 为用户前序未跟踪工作，保留原内容；本轮仅新增实验文档和追加规划记录。

- 项目由 platform、teacher_agent、student_agent 三个服务构成。
- student_agent/README.md 描述新 FastAPI + LangGraph + Next.js 静态导出结构。
- docs/student-runtime-mechanism.md 和 platform/docs/student-agent-integration.md 含旧 orchestrator、legacy 目录引用，不能直接作为当前实现依据。
- 下一步对照 backend/main.py、agent/*.py、StudentApp.js 和平台 student_bridge.py。

## 当前代码确认
- 前端 Next.js output=export、basePath=/app，FastAPI 挂载 frontend/out；StudentApp 使用本地状态切视图、普通 HTTP 请求，知识点准备中每两秒轮询。
- 平台负责登录选课、已发布目录、短期签名令牌、当前课时上下文；教师端播放器由 iframe 复用，以 postMessage 返回播放事件。
- start 只取目录；begin 按 lesson_id 获取单课时，校验 user/course/publication/version，先持久化 video/pending 再后台提取知识点。
- 知识点材料仅为当前课堂场景画面文字和旁白；模型输出经原文证据校验，存在部分有效结果时可继续，完全失败则重试。
- 外层服务 phase 为 idle/video/discussion/done；replay、postclass 主要是前端视图，课后 API 保持后端 phase=done。内层 stage 为 recall/reinforce/discuss/wrapup。
- LangGraph 每轮 evaluate→route→respond；LLM 判断和生成，progression.py 决定阶段推进。首轮默认8轮、加强4轮，首轮第6轮后掌握还需确认；讨论每个合格知识点一题、答对推进。
- 反馈按本次评估历史确定，概念结果与讨论结果分开；课后补完再开放自由提问，反馈更新且保留课堂原反馈。
- 数据写入 student_sessions/student_messages/knowledge_mastery/learning_events；完成反馈、最终快照和 ended_at 在一事务内提交，其余写入分事务。
- 默认 fresh_session_mode=1：运行态进程内字典，浏览器保存签名完整快照，数据库仍写记录；不默认从数据库恢复跨浏览器历史。
- 平台存在 learning-progress 推送教师接口，尚需确认新学生端是否调用。平台 percent 是开始过的不同 classroom 数/发布课堂工件数，不等于掌握率或严格完成率。
- 已检索全部 student_agent 代码：没有 learning-progress 调用；SCENE_COMPLETED 回调在适配器中可选，但 StudentApp 未传该回调。播放完成只更新提示，讨论按钮没有强制视频看完条件。
- 已生成 student_agent/docs/student-architecture-current.md，明确未进行线上状态或端到端验证。

## 新方案输入核查
- 用户明确优先“理解与应用”，能够解释概念并解决新问题。
- 教师端 types.ts 已定义课时 objectives、七类课时文件（目标/知识点/活动/页面/旁白/习题/评价标准）、习题和评价量规产物、知识图谱先修关系；这些是代码能力，不保证每课都有已发布且合格内容。
- 产物 content 以 Markdown 为主，不能假定习题已有统一答案与评分 JSON；published entries 和平台拼装的条目字段存在差异，应在平台适配层统一。
- 当前 iframe 适配有场景完成事件接收，但未发现该适配中的暂停/指定场景跳转控制接口。新版分段教学必须列为新增集成能力，第一期可保留整段播放。
- research 技能要求后台研究，已委派 learning_evidence 子代理，仅负责研究依据文档。
- 建议方案：课时教学包（教师目标与已发布材料对齐）→诊断→学习→按错误提供帮助→新题独立验证→延迟复查；第一期保留整段播放。
- 教师端课程 service API 可输出已发布文件、产物和已发布图谱，但现有学生主链仍经平台，建议统一平台适配层。
- 发布链路显示不能仅以课程总包版本缓存；建议各资源发布ID与内容hash组成 manifest，保证教学包与历史证据版本可追踪。
- 研究依据支持检索、解释、例题/练习交替及延迟检测；对 LLM 学生端的实际学习收益需教师校准与真实学生试点验证。

## 用户纠正与当前约束

- 用户指出当前实际主要是教师原版 PPT 与生成 HTML 课件，其余产物没有强制保障。设计必须以这两项为基线，不能要求先补齐目标、知识点、题库与评分标准。
- 整段播放保留是明确约束，后续讨论聚焦播放后；移除分段播放作为方案升级目标的表述。
- 继续按 research 技能使用产品官方信息，子代理研究 NotebookLM/StudyFetch，主代理研究 Quizlet/Khanmigo。
- 补充查证：部分课件生成和归档路径确实调用 ensureLessonReviewFiles，但新增目标/知识点文件为 draft；不能把它们当作已发布、必有学生输入。
- 产品官方说明支持材料→任务→解释/出处、按正误聚焦困难、可调整的活动流程与题中辅导；都不能直接证明我们的教学有效。
- Khan Academy 2026 产品报告用 next-item correctness 检查辅导后的无帮助同技能新题表现，值得借鉴，不能等同长期或远迁移效果。
- 已把方案修订为 v0.2：PPT+HTML 基线、固定整段播放、播放后比较复述/短任务/案例入口；取消默认课前诊断和分段播放升级路线。

## 用户确认主路径

- 用户同意先用几个具体问题初步了解学生，再根据回答进行后续辅导；已更新方案 v0.3。
- 建议按理解点保存独立表现、具体误解、应用困难与未覆盖，避免只有总分。
- 待讨论细则：小组题先收原始回答再完整辅导；澄清与内容提示分开，提示后回答标为受助证据。
- 播放后的初步状态不等于课前基础，不能仅凭此宣称视频学习增益；后续新题可观察辅导后的独立表现变化。

## 真实产品流程补查

- 用户要求基于外部真实方案建议；上一轮四种自拟流程不作为当前产品选项依据。
- 新增 ALEKS 官方流程：初始独立检查→个性化学习路径→周期复查；诊断不即时显示正误，学习模式提供分步解释与新题。其课程级20–30题机制不能等同我们的几道课后题。
- 补查 StudyFetch Results：连续错误较多会暂停推进建议复习，暂停/完成后推荐 Tutor 等工具；Guided Chat 是另一显式入口，不能伪称所有诊断完成后自动进入定制补救计划。
- NotebookLM 已确认生成测验/提示/解释/回顾，但未确认测验自动驱动完整补救路径。
- product-native-workflow-options.md 保存原生流程、官方来源和适配边界；当前建议从输入匹配角度优先参考 StudyFetch，ALEKS用于诊断机制对照，不宣称效果优劣。

## 最新用户选择（方案 v0.4）

- 用户标注短任务优先，并确认视频后用几道简单题初步整体了解掌握情况，再由大模型安排辅导。
- 整体概况关联逐题原始回答、判定依据与未覆盖范围；不等于仅凭总分断定整课掌握。
- 教师输入继续为 PPT+HTML；后续题量、题型、反馈时点仍待确定。更新文档，没有实施后端。

## 三环节细化（主方案 v0.5）

- 用户已确认题型：选择/判断为主＋一道简答。建议默认4题（3＋1），仍待讨论，不宣称最优。
- 生成链：来源与覆盖→蓝图→候选题/答案/要点→质量检查→版本固定；保留原文校验但承认其不能证明语义正确。
- 判断链：规则判客观题，模型按预设要点评简答；按理解点汇总，保留矛盾、受助、未覆盖与系统不确定，避免正确率等同掌握率。
- 辅导链：模型基于证据提出短计划和活动；程序校验来源和可用动作，后续证据触发调整；支持下完成与新题独立完成分别记录。
- 已形成说明性四题案例；刷新外部依据用于确认检查/教学分开、困难先复习及同技能独立新题指标。新增细化稿与主方案更新，未实施代码。

## 用户质疑与重新审视

- 用户认为单答案客观题信息有限、每课简答提示词可能不同、固定表现分类不自然。暂停把固定4题＋标签分流作为当前推荐，不自行替换为新已定方案。
- 当前代码已经使用通用 EVALUATION_PROMPT/TUTOR_PROMPT 并注入课时 points；逐课人工改提示词不是必要条件。真正的跨课挑战是正确的材料解释、判据与专业任务校验。
- 当前提示词要求固定 focus 顺序，progression.py 用状态和轮次推进；仅扩展状态枚举不能解决机械辅导体验。
- 已复核 NotebookLM Learning Guide 的开放追问/分步帮助官方说明、Khan Academy 结构化作答记录测试；可作为动态对话/具体证据的参考，不假定已公开内部评估算法或证明本项目有效。

## 动态对话环节设计（v0.6）

- 用户同意尝试具体问题→动态追问/补讲→持续证据→独立表现，要求逐环节设计。
- 当前设计：后台内容地图；一个具体问题打开；按真实表达澄清/解释；每轮保存原话、理解依据、疑问与帮助；适时新情境；按实际覆盖和帮助情况收尾。
- 同一对话内交替活动，理解记录不是单独评分环节；结构可固定，语义与教学选择不由掌握等级直接驱动。
- 新增 dialogue-tutoring-design.md，主方案更新 v0.6，旧4题稿保留历史参考；未实施代码。

## 程序主导控制权（v0.7）

- 用户明确程序运行预设流程，AI 只负责当前教学任务；不允许 LLM 自主切阶段、改任务序列或结束。
- 当前职责：程序创建 TeachingRequest、维护任务与阶段、接收明确事件、校验保存并推进；AI 输出教学内容与观察草稿，不输出可执行的 nextPhase/结束命令。
- 活动执行完成和学生已掌握分开记录；程序不能仅靠代码证明开放回答的语义理解，模型观察也不是自动推进授权。
- 保留现有 progression.py 用代码管理推进的原则，重新设计过度机械的活动规则即可，不将调度权搬入模型。

## 最新澄清：Agent 决策，程序推进（v0.8）

- 用户纠正“继续当前主题/换主题/独立尝试应由程序决定”：应由 Agent 根据证据决定，程序校验执行。
- 预设主线与合法动作仍归代码；Agent 返回带任务和状态版本的受限动作，程序检查前置条件并幂等迁移，不执行自由文本指令。
- 教学决策与内容生成是逻辑职责，不必增加多个独立 Agent。主方案及对话设计已同步，未改业务代码。

## DeepTutor 架构源码核查（2026-10-29）

- 固定上游 commit：1ea7df155447f4caf0e3abc86b3ff5395479cd4a；提交时间 2026-10-29 00:36:18 +0800。参考检出在系统临时目录 codex-deeptutor-architecture-20261029，不纳入业务仓库。
- 当前源码为 1.7.0 模块化布局（区别 README 中最新稳定版 1.6.15），核心路径 deeptutor/，不能复用旧 src/agents 的定位。
- 直接源码：app/service.py 的 TurnApplicationService.start_turn 有 client_submission_id + digest 去重；subscribe_turn(after_seq) 从持久事件和 coordinator 重放。runtime/orchestrator.py 按 active_capability 路由，默认 chat；不是按名称即多个 agent 自主协作。
- 核心协议：core/context.py UnifiedContext；core/tool_protocol.py BaseTool；core/capability_protocol.py TurnCapability；core/stream.py StreamEvent。需要借鉴职责，但不必复制其注册器与运行时。
- 本轮一次 rg 传递 Windows 路径内 app/turn* 不支持，已切换目录加 -g 参数。规划技能的 catchup 脚本缺失，沿现有规划恢复。
- 已追踪默认聊天链：ChatCapability.run → AgenticChatPipeline（继承共享 AgenticLoopPipeline）→ AgentLoop.run；可选 TypeScript native 引擎通过环境变量分支启用。研究默认 Python 链路时不将它误称 LangGraph 实现。
- StreamEvent 包含 type/source/stage/content/metadata/session_id/turn_id/seq；前端 TurnRuntimeClient 单独负责连接、命令确认、序号与重放，避免把 WebSocket 与组件业务混在一起。LangGraph 流式只是事件来源，浏览器重连与重放仍需应用实现。
- ContextBuilder 预算化近期历史与滚动摘要；UnifiedContext 区分序列化输入、临时 runtime 与 capability_output。当前学生端只取最近8/10条，后续需要结构化教学证据，不能仅靠摘要替代学情事实。
- 上游 services/rag/factory.py 默认 provider 为 llamaindex，支持多个后端；DeepTutor 不是 LangChain 换壳。借鉴检索接口与出处约束，无须迁入所有引擎。
- 附加路径检查 services/session/context 目录不存在，已定位真实 context_builder.py 文件，无需重复失败命令。
- 教学源代码已复核：MasteryLoopCapability.pre_loop、mode.TOOL_MODES 与 _wrong_mode_result、PendingQuestion、grade_interaction 的幂等事务、ReadingCapability 的视口上下文。按原定位误查 reading/capability.py 不存在，已改为 capabilities/reading/capability.py。
- 主报告建议保留现有平台集成，借鉴六项领域设计；现有图不强制使用 interrupt 等待每次学生输入，也不必为参考能力设计先建立插件系统。恢复明确分为图执行、学习业务、浏览器展示流三层。
- 已完成三份文档引用静态检查：58处固定上游源码链接、55处本地链接、8处框架文档引用；所有上游/本地源码路径及行号有效，0错误。源码静态分析不代表运行或教学效果验证。

## 大陆迁移核查（2026-10-31）
- GitHub 仓库 huanche/agentic-class-pilot；本机 gh 已登录且有 repo/workflow 权限。
- 远端存在 mainland-tcr-push-test.yml；运行 41188260252 正在执行，尚无成功证据。
- 远端所需 MAINLAND_* 和 TCR_* Secrets 名称均存在，未读取密钥值。
- 本地 lzm2 分支落后于远端部署配置，且学生端存在既有未提交修改，不能直接推送当前工作树到 main。
- known_hosts 包含 43.138.178.158；support 密钥登录该地址 root 被拒绝，地址角色仍需通过成功连接确认。

2026-10-31续：香港与大陆应用源码均ed8d193，和当前main三端目录无差异；香港browser_session563，大陆562，其余抽查学习/课程计数相同，不等同完整内容一致。大陆外部接口10.1.0.4；已生成Caddy候选配置，default_bind/bind限定10.1.0.4并通过Caddy2.10校验，未启用，避免172.19.0.1:443出口占用。平台/学生现有systemd迁移隔离仍在、启动服务未配置生产自启。腾讯云官方https://cloud.tencent.cn/document/faq/243/20220说明大陆网站需完成备案/接入备案；已询问用户现有域名及备案状态，未假定已完成。本机代理DNS把域名解析为198.18.0.10（fake-IP），不能作为公网权威DNS证据。
