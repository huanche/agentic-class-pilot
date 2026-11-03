# 学生端 P3：稳定任务、证据、帮助与内容版本

日期：2026-11-02。对应[模块架构设计](student-module-architecture-design.md) P3，接续 [P2](student-p2-implementation.md)。本次完成本地实现和隔离回归，未部署、未操作正式数据库。

## 1. Module 职责与实际落点

| 文件 | Interface 与职责 |
|---|---|
| [learning_records.py](../backend/evidence/records.py) | 纯函数 normalize / transition / validate：稳定身份、任务与消息绑定、观察和帮助关联、历史未知项、安全任务视图及反馈引用；不调用模型、不写数据库 |
| [lesson_content.py](../backend/content/lesson_content.py) | build / bind / validate：纯来源清单、主题地图、内容指纹及绑定；内容包含教师材料，不包含学生表现 |
| [content_store.py](../backend/infrastructure/content_store.py) | 目录整理后 store / find / hydrate 归入 PostgreSQL Adapter；不可变版本保存和按固定引用恢复，沿用原事务 |
| [published_knowledge.py](../backend/infrastructure/published_knowledge.py) | 保留既有准备任务、领取与重试，将每份成功结果保存为独立内容版本；旧结果先归档，避免升级覆盖 |
| [persistence.py](../backend/infrastructure/persistence.py) | write_records 与 write_state 用同一连接保存消息标识、任务、观察、帮助、快照与反馈；恢复按 contentRef 读取原版本 |
| [commands.py](../backend/infrastructure/commands.py) | 接收时绑定 task_id、student_message_id、content_id；重复、重试、接管和完成继续使用 P2 的版本与租约约束 |
| [teaching.py](../backend/teaching/service.py) | 保持原教学图；送给模型的近期消息过滤追踪字段，保留原 role/text/phase 输入约定 |
| [rec12 迁移](../../platform/backend/app/alembic/versions/rec12_student_learning_records.py) | 增加标识列、内容版本表及索引；显式撤销 student 角色对内容版本表的 UPDATE/DELETE 权限 |

顺序、轮次、掌握判断、讨论推进、课后待办和既有反馈标签沿用原实现。本期没有新增题组、动态调度策略、独立验证环节或额外模型调用。P4 才接入动态教学动作。

## 2. 稳定身份与任务语义

| 对象 | 稳定标识与事实 |
|---|---|
| Message | messageId、episodeId、taskId、createdAt、recordOrigin；命令产生的消息由会话/内容代次/命令/角色确定，重试不换 ID |
| 历史 Message | 由会话/内容代次/原序号生成确定性 ID；不猜历史 taskId 或时间，保留 null 与 legacy_unknown |
| Episode | 同一课堂与课后活动使用不同 episodeId；同一活动重复进入复用标识 |
| Task | 按会话、内容代次、活动、教学阶段和知识点确定 taskId；类型为 recall / reinforce / discuss / postclass_*，自由提问每次产生独立 open_question |
| Observation | 由学生消息确定 observationId，引用本人实际消息、原话、任务、主题、来源和此前帮助；模型判定与学生原话分字段保存 |
| Assistance | 由导师消息确定 assistanceId，引用对应任务和活动、实际保存的回复及程序选择的教学策略 |

Task 保存 purpose、sourceRefs、首次已记录的 questionMessageId/question、后续 promptMessageIds 和执行状态。新任务的问题在回复成功保存时绑定，之后不得看到回答再改原题。旧任务没有可靠原题时保留 null，后来的提示不会被冒充为此前的原题。

同一轮学生发言关联推进前的任务；导师回复可能关联推进后的任务，并通过 relatedTaskIds 保留前后关系。这样不会把“上一知识点的回答”归到导师刚进入的新知识点。

课后继续原讨论时，若课堂讨论任务已有记录，新增任务通过 resumesTaskId 指向原任务；课堂与课后使用不同活动标识。历史缺乏可靠任务关联时，不按文本相似度猜测。

提交可以携带 `payload: {text, taskId}`。后端校验当前任务，错误任务返回 TASK_CHANGED，且不运行模型、不推进版本。旧 P2 `{text}` 命令继续可用；前端重试旧在途提交时保留原载荷，避免增加 taskId 后破坏幂等哈希。

## 3. 学习证据与帮助记录

新 Observation 的 studentExcerpt 必须等于被引用学生消息的实际文本，引用导师消息、其他任务、外课来源或未来帮助都会被拒绝。modelRationale 是已有模型判断的解释，不作为学生原话。没有模型判定时标记 unknown/no_assessment，不补造正确或错误结论。

帮助记录区分三件事：

- 已提交的导师回复：assistantMessageId、providedAt、deliveryStatus=committed。
- 程序执行的指导策略：hint、correct、answer_question、remediation_response 等；guidedPolicy 表示程序选择了此类回复策略。
- 无法单凭程序确定的语义帮助程度和实际阅读：substantive 保留 unknown/null，不宣称学生已阅读或帮助有效。

providedAt 是回复候选记录生成时间，只有完成事务提交后才成为可查询记录；没有浏览器阅读回执。后续回答若发生在已记录的指导策略之后，标记 assisted 并列出 assistanceRefs；否则仍为 unknown。当前流程没有无帮助独立验证契约，不新增 independent 结论。

一轮刚生成的提示属于本轮回答之后，不能反向证明此前回答受助。不同任务的帮助不能混用。新的相反表现追加为新观察，已提交的观察、帮助和原题保持不变。

旧 assessment_history 可以保留为 legacy_unknown 观察，但 studentMessageIds、taskId、帮助关系和独立性保持未知。相同文本反复出现时不按猜测关联消息。旧记录仍支撑原有反馈，不因增加追踪结构重算成绩。

个人反馈增加 observationIds、evidenceLimitations 与 evidenceSummary，保留原概念/讨论结果和反馈标签。课堂原反馈与课后更新继续分开保存；这些计数不是整课掌握率，也不证明教学效果。

## 4. 版本化课时内容

LessonContent 包含：

```text
contentId / schemaVersion / courseId / lessonId
sourceRevision / compilerVersion / sourceManifestHash
sourceManifest[]    场景定位、来源类型、文本指纹
sources[]           实际可读的课堂文字和旁白
topics[]            主题、对应来源与可定位原文引用
points[]            原有教学链使用的知识点定义，不含学生状态
coverage / coverageGaps / validationStatus / inputCapabilities
```

contentId 校验完整内容指纹；来源清单、文本指纹和引用也分别校验。主题引用必须属于本课该版本，原文必须可定位。source_checked 只表示来源检查通过，不代表语义正确或教师已确认。

数据库允许不同 sourceRevision、整理器版本和来源清单并存。内容格式版本与原提取器哈希共同组成 compilerVersion。已完成的相同版本不能被另一份模型输出覆盖；student 运行角色只能 SELECT/INSERT 内容版本。

当前可靠输入仍是播放器场景文字和可取得的 speech。原 PPT 未通过平台接入完整解析，inputCapabilities.originalPpt=false；图像/图表不冒充已识别，可能截断的长文本和来源缺失会记录 coverageGaps。本期没有把 PPT 完整解析变成前置条件。

旧共享准备结果在读取或处理时无模型归档到结构化版本；只增加结构不重新调用模型。真正的提取器变化仍运行原准备链，但旧版本保留。准备 worker 的旧领取凭据或过期租约不能发布内容版本。

开始学习后固定 contentRef。整理器升级不重建当前会话、不清空已学状态；新的会话可以使用新版本。原视频重新发布仍由既有进入/恢复检查识别，递增内容代次、清除本会话旧学习，并初始化新版。

旧快照只有知识点时，将其干净的内容定义冻结为 legacy-frozen 版本，来源不足明确标记未知。没有原视频修订号时使用 legacy-unversioned，不伪造来源版本。恢复时原绑定版本缺失会报错，不静默切换到最新内容。

## 5. 保存、恢复和查询

任务、观察、帮助与活动作为 learning_task、learning_observation、learning_assistance、learning_episode 记录保存在 learning_events；消息表增加 message_id/task_id/episode_id 列。任务定义保持稳定，状态和已发提示列表可以更新；观察和帮助仅追加。持久化层只写相较上一快照变化的记录。

它们和 P2 的消息、掌握结果、反馈、权威快照及命令完成回执使用同一事务。失败时全部回滚；原命令和原回答仍保留供重试。旧消息标识按需回填，之后重复恢复、重试及重登保持一致。

SessionView 增加 currentTaskPublic、contentRef、recordSchemaVersion，消息携带稳定标识。前端沿用原页面与操作，只将任务标识随回答发送，并优先使用 messageId 作为消息视图 key。

新增授权查询：`POST /api/session/{sid}/learning-records`，请求体 `{launch_token}`。返回本人活动、任务、观察、帮助及内容限制；校验身份后只读，不运行模型、不写学习记录。

正式 browserSnapshot 现在只含签名定位信息：会话、可信范围、课时、阶段与版本线索，messages/courses 为空。不整体下发内部教学状态、内容正文或证据库。恢复仍重新鉴权并读取数据库。独立演示模式保留原浏览器恢复方式。

重置删除本人本课消息、任务、观察、帮助和命令数据，保留 P2 的最小撤销标记。共享课程内容不属于某个学生的学习记录，因此保留供其他学生及新学习使用。

## 6. 迁移和回退

本次未发布。后续按以下顺序执行：

1. 暂停 P2 旧进程写入并等待在途处理结束，保留数据库备份。旧二进制不维护 P3 的追踪结构和内容引用，不能与 P3 并行写同一库。
2. 在平台正常迁移环境执行 `python -m alembic upgrade head`，先完成 cmd11，再完成 rec12。
3. 发布 P3 学生后端及其前端构建，启动原知识点准备 worker 和命令恢复 worker，再恢复入口。教师/平台原内容登记协议无需新增必交付材料。
4. 核查旧会话、原版本恢复、记录查询和课后反馈。必要时使用 P2 的 `STUDENT_COMMAND_ACCEPT_NEW=0` 排空新命令。

回退保留新增列、内容版本与证据；不能删除它们来回退，也不能启用会覆盖这些字段的旧写入实现。rec12 downgrade 不销毁学习数据。当前结构仍为单体进程内 Module，不引入额外部署或消息队列。

## 7. 回归与适用范围

验证命令沿用 P2：配置专用回环 PostgreSQL 的 STUDENT_TEST_DATABASE_URL，再运行 `.venv/Scripts/python.exe -m pytest -q student_agent/backend/tests`；在 frontend 运行 `npm run test:unit`、`npm run test:e2e`、`npm run build`。隔离连接只接受 student_p2_test 管理用户和 postgres 管理库，自动创建/删除随机测试库，不读取正式/开发库连接。

本次最终结果：后端 144 项通过，其中 46 项为真实 PostgreSQL 场景；前端单测 21 项、浏览器 12 项通过，生产构建成功。

新增覆盖包括：

- 原题在回答前绑定、任务跨阶段与跨活动关系、命令重试标识、历史 unknown 兼容和消息列回填。
- 学生原话校验、导师消息不得作为学生证据、未来帮助拒绝、来源隔离、已提交证据不可重写。
- 记录写入失败后的消息/证据/帮助/任务整体回滚，重试后身份不变；授权记录查询与重置删除。
- 同一课时版本共享、原文引用、内容不可覆盖、整理器升级并存、旧会话固定引用、准备失败重试与旧 worker 结果拦截。
- 原 P2 并发/崩溃恢复、既有 8/4 轮与课后反馈、平台进度等回归；真实 student 角色在继承旧默认授权后仍无权 UPDATE/DELETE 内容版本。
- 前端新回答绑定当前任务、P2 在途提交升级后原载荷不变、丢失回执重试、刷新恢复和回看。

数据库操作真实执行，模型与平台授权使用隔离替身。旧兼容用例继续比较所有原有消息/反馈业务字段，新增追踪字段另有稳定性与来源测试。未验证真实模型教学质量、完整 PPT/视觉解析或生产容量，不把记录结构完整等同于语义判断可靠。
