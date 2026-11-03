# 学生端 P4：受限动态教学试点实现

日期：2026-11-02。接续 [P3](student-p3-implementation.md)，对应[架构设计](student-module-architecture-design.md) P4。本次交付可配置的试点执行能力、证据反馈及本地回归。默认仍为 legacy；未部署、未启用正式试点。真实课时和真实模型的抽样质量验收尚未进行，不能视为已通过 P4 的教学质量退出条件。

## 1. 现有行为和启用范围

无配置、配置无效、非白名单课时、演示模式及旧会话继续使用 `legacy_recall_v3`。保留原提示词、逐点复述、8/4 轮、评分、深入讨论、课后补完及视频换版清理行为。P4 不将旧学习记录改造成动态流程，也不读取旧最高星级来安排动态教学。

试点配置仅作用于正式身份下新开始的课时。后端使用已验证平台上下文里的 courseId 和已选 lessonId，不接受浏览器指定 flowVersion 或规则。配置示例（仅说明，未对运行服务设置）：

```powershell
$env:STUDENT_DYNAMIC_PILOT_SCOPES = '[{"courseId":"经过抽样核验的课程ID","lessonId":"经过抽样核验的课时ID"}]'
```

选择 `dynamic_dialogue_v1` 后，将 flowVersion 和完整 teachingPolicy 保存进权威快照。进入 video 后不允许改写；恢复、重试、关掉白名单均继续原流程。视频重新发布仍清理本课学习，内容代次递增，保留会话原流程和规则。真正重置后创建的新学习按当时配置重新选择。

当前试点规则为 `dynamic-pilot-v1`：每场课堂/课后活动最多 12 次输入，同一任务最多连续 4 次输入后不再允许原题继续；正常模型收尾需先有至少一次独立任务回答。学生主动结束与负担上限均可退出，不要求答对。达到整场上限由程序直接收尾，不再额外调用模型，也不为最后输入编造语义结论。参数是待试点校准的初值，不是经过验证的最优教学负担。后续调参需新增版本并保留已存在版本的执行支持。

## 2. Module、Interface 和状态

| Module | Interface 和职责 | 状态归属 |
|---|---|---|
| [teaching.py](../backend/teaching/service.py) | select_flow、describe_session、start_discussion、classroom_turn、finish、start_postclass、postclass_turn；统一选择两个实际教学 Adapter | 不单独保存 |
| [dynamic_teaching.py](../backend/teaching/dynamic_teaching.py) | plan/start/turn/finish/postclass/activity/describe；根据固定内容和规则生成、验证候选结果，不操作数据库或平台 | teachingState、预定任务定义及决策候选 |
| [learning_records.py](../backend/evidence/records.py) | 沿用 normalize/transition/validate；将原回答、任务、观察、帮助及 TeachingDecision 绑定并验证不可变字段 | learningRecords 的持久记录投影 |
| [commands.py](../backend/infrastructure/commands.py) 与 [persistence.py](../backend/infrastructure/persistence.py) | 沿用 P2 接收、领取、CAS、租约和事务；P3 同一连接写入任务、证据与决策 | 权威快照、命令回执和 learning_events |
| [model.py](../backend/infrastructure/model.py) | 新增 complete_bounded；在客户端创建时应用超时和零 SDK 重试，legacy complete 的配置保持原值 | 无业务状态 |
| 前端现有页面 | 消费服务端任务阶段、活动覆盖和事实反馈，仍在同一对话框；不执行动态推进规则 | 展示及原输入草稿 |

动态 TeachingState 保存 stage、task、turns、taskTurns、taskOrdinal、coveredTopics、returnPoint、episodeKind 和 activityStatus。当前 task 是教学执行需要的固定任务定义；learningRecords 保存其不可变原题/依据及后续消息引用，读取时核对关键定义一致。新任务不能复用旧 taskId；任务 ID 按会话、内容代次、活动种类和序号稳定生成。

内部阶段为 opening、tutoring、independent_attempt、summary、completed；外部生命周期仍为 idle → video → discussion → done。summary 兼容投影为 agentStage=wrapup，现有结束入口完成保存；不会读取“进入下一阶段”等自由回复推进。课后在 done 下使用 after_class 活动，任务 ID 与课堂隔离，不将课堂改回 discussion。

## 3. 受限决策、生成和失败

模型只能提出 continue_topic、switch_topic、start_independent_attempt、request_summary，以及存在返回点时的 return_to_task。程序先计算 allowedActions，再校验：

- basedOnStateVersion 对应接收前的权威状态；taskId 对应当前任务。P2 接收后的技术版本及租约仍在完成事务独立比较。
- 目标主题属于固定 contentRef，并有实际校验过的原文引用；不能使用来源未知主题进行试点评价。
- reasonEvidenceIds 必须属于本场活动中已有的观察；当前输入另以 studentMessageIds 绑定到原提交。
- 新任务在回答前固定 question、purpose、criteria 和 sourceRefs，独立尝试使用新任务和不同原题，不预设提示策略。
- 原任务继续不能悄悄换主题；独立阶段提供提示后会留下帮助记录；同题和整场负担均受程序约束。
- 生成回复绑定已验证的 taskId 和来源，必须包含新任务原题；不能借生成回复改写已验证策略。

一次决策不合法，至多要求模型修复一次；仍不合法则返回 INVALID_DECISION 并保留原提交。回复绑定不合法直接失败。每轮总预算 90 秒，每次模型请求最多 25 秒、SDK 重试为 0；通常两次调用，决策修复时最多三次。过期结果也不能提交。网络层超时之外，不承诺任意失效第三方客户端可被强制中断；完成仍由 P2 租约和版本拦截。

模型只接收本课来源、当前任务、规则、相关观察、帮助和近期文本，不接收平台密钥、数据库连接、其他课程或整个 SessionRecord。来源和学生文字是数据，不授予修改程序规则的权限。程序验证结构和引用，无法证明自然语言题目完全无暗示、引用支持其全部语义或追问教学质量可靠；这些保留给抽样评审。

## 4. 证据、独立任务和反馈

每个实际回答都绑定回答前任务，保留学生原话；消息阶段也保持回答前阶段，下一题提示使用推进后阶段。观察的 supportedUnderstanding/uncertainties 是模型解释，标明 semantic_judgement_unverified。导师原文不能变成学生表现，旧观察与帮助不能重写。

独立任务的标准在发题前固定。没有本任务提示记录时标记 `no_recorded_help_in_task`，并保留任务外帮助未知限制；这只表示本系统没有记录该任务内帮助，不证明独立理解或长期掌握。提示、例子和讲解按执行策略记录，之后的回答可标记 assisted；回答后的帮助不能回填解释早先回答。帮助的实质作用、学生是否阅读仍未知。

TeachingDecision 按稳定 decisionId 保存在 `learning_events` 的 teaching_decision 类型，同时保留在 learningRecords；与消息、任务、证据、帮助、反馈、快照、命令回执同事务。失败会整体回滚，原命令 ID、任务 ID 和学生消息 ID 用于重试。临时候选 dynamicTurn 不进入数据库快照。

反馈由已有记录确定性构建，包含学生表达、带引用的模型解释、受助情况、未解疑问、未覆盖主题和来源缺口；不依赖额外总结模型，也不输出动态掌握星级或整课掌握率。旧反馈字段作为兼容投影保留，动态页面不显示旧轮次和掌握统计。结束时固定 classroomFeedback，课后生成新的 current feedback，保留原课堂反馈。

## 5. 命令与页面兼容

正式教学继续走原命令入口 `POST /api/session/{sid}/commands`，携带 launch_token、commandId、expectedStateVersion 和 contentGeneration。动态回答额外要求当前 taskId，避免将旧回答挂到新题。旧 legacy/P2 在途载荷兼容不变。

| type | payload | 动态流程约束 |
|---|---|---|
| start_discussion | {} | 视频内容已准备；已有 discussion 则不重复发题 |
| submit_answer / postclass_answer | {taskId, text} | 对应课堂/课后活动未暂停、未总结，文本 1–2000 字符 |
| request_help / ask_question | {taskId, text} | 显式记录请求；跨主题询问保存原任务返回点 |
| pause / resume_activity | {} | 保存原任务，不重新发题；暂停不调用教学模型 |
| finish | {} | 视频、讨论或课后活动均可结束；取消在途结果，未交流内容保持未覆盖 |
| continue_after_class / reset_lesson | {} | 仍要求课堂已 done，沿用既有授权和删除语义 |

SessionView 增加 flowVersion；动态视图返回 teachingStage、activityStatus、allowedCommands、allowedActions 和 progressSummary。后端仍重新验证所有操作。失败命令沿用 P2 的 HTTP 503 回执，具体 failure.code 区分 INVALID_DECISION、MODEL_UNAVAILABLE 等；接收前的非法操作仍为 409/422。

当前页面增加动态阶段和事实反馈的兼容显示，并为动态课堂提供正常结束入口；legacy 页面文案和操作保持原样。请求/订阅全面收拢、暂停/求助的专用按钮、更正展示和更多结构化交互仍属于 P5，本期新增命令可通过正式 Interface 验证。未接入自动中断整段视频或新考试页。

## 6. 回归和试点质量门槛

验证方式沿用 P3：专用回环 PostgreSQL 自动创建/删除随机测试库；真实执行 cmd11/rec12 后验证事务。模型和平台访问使用可控替身，未访问正式库。

本地验证覆盖：

- 白名单错误默认关闭、正式开课固定流程、旧会话不升级、关白名单后恢复原动态任务。
- 问题/来源/依据提前固定，不同输入对应的合法追问与独立任务结果；非法动作、过期版本、错任务、假来源、假证据、复用原题和不匹配回复拒绝。
- 一次修复、总超时、原题和整场上限、独立新题、提示后的受助关联、明确结束、暂停恢复及跨主题返回。
- 真实数据库命令幂等、决策/证据/任务整体回滚、原回答重试、重启恢复、两设备竞争和结束后迟到结果拦截。
- 课堂反馈保留与课后独立活动；原 8/4 轮、共享准备、换版、回看、平台进度与 P2 并发恢复回归。
- 浏览器消费服务端任务 ID、动态阶段/覆盖展示、直接结束与证据反馈；原 legacy 浏览器场景继续通过。

最终后端 **173 项通过**（122 离线、51 真实 PostgreSQL，84.76 秒），前端单测 **21 项**、浏览器 **13 项**通过，生产构建成功。Python 编译、本地文档引用与 git diff --check 通过。专用测试库剩余 0，已核验数据目录归属并停止测试集群；Next 自动生成的 AGENTS.md 已清理。回归不证明真实模型能根据不同回答作出高质量追问。

启用试点前选一节实际已发布、原文可读的真实课时，固定其 contentRef，人工核对所有试点主题及来源。用同一原题分别尝试含糊回答、有条件的合理回答、误解、不会、复述提示和完整解释，抽查下一问是否回应原意、是否重复、是否泄露独立题答案，以及反馈是否误把导师表述当作学生证据。还需检查公式/图示缺口与专业事实。记录模型版本、contentRef、policyVersion、原回答、实际追问、证据 ID 及评审结论，未通过则保持白名单为空；本次没有伪造这份真实质量验收记录。

## 7. 发布与回退

本期无需新增数据库迁移，依赖 P3 rec12 已执行。发布时排空旧进程写入，再更新后端与前端；P3 二进制不知道动态状态，不能与 P4 混写。默认空白名单可先验证原流程，未通过上述抽样前不启用正式试点。

关闭白名单只影响新学习；已有 dynamic 会话继续由支持 dynamic_dialogue_v1/dynamic-pilot-v1 的实现恢复、重试和结束。回退应保留 P4 兼容执行能力并关闭新准入，不能直接换回不识别动态会话的 P3 二进制。学习记录、决策、原课堂反馈与固定内容版本均保留。未部署、未提交 Git 提交或推送。
