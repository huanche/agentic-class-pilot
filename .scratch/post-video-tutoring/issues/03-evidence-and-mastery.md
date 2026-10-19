# 03: 作答证据与知识点星级

**What to build:** 辅导对话的知识点内考核循环：AI 出题（诊断题/确认题）→ 学生作答 → 判定对错 → 更新该知识点系统星级。每次 AI 出题记一条出题事件（题目摘要、考点、时间、是否有提示）——demo 态 JSON 落盘、平台态写 learning_events。只有"判为实际作答且可判定对错"的消息进入评估；答错触发针对错误的追问或讲解。有提示的作答不计入"无提示独立答对"证据。平台掌握表加自评列（与系统星级同排不同列、分开读写）。前端掌握条显示每知识点的系统星级与自评。

**Blocked by:** 01

**Status:** resolved

- [ ] 出题事件按持久化分层落库（demo JSON / 平台 learning_events），含题目摘要、考点、时间、提示标记
- [ ] 有效作答更新对应知识点系统星级；非作答消息（追问/求助/闲聊）不更新（各有测试例）
- [ ] 有提示的作答不会被记为"无提示独立答对"证据
- [ ] 平台 alembic 迁移：knowledge_mastery 加自评列；读写走持久化层，缝 B 测试
- [ ] 掌握条展示系统星 + 自评，随作答实时变化
- [ ] 答错后的教学动作是追问/讲解而非直接给答案（确定性桩可测分流）

## Comments

### 2026-10-20 Claude（工单 03 实施）

**做了什么**（4 个红-绿切片）

- 检测题机制（`orchestrator/agent.py` teach 的 tutoring 分支）：进入知识点先出确定性检测题（`_tutoring_diagnostic_question`，无模型也照问）；答题类消息交给 `_tutoring_judge`（模型判 correct/wrong/unclear，输出一行 JSON；无模型一律 unclear——不瞎判、星级不动，测试在此 mock）。判对：无提示 +1 封顶 5、有提示最多记 3（对应草拟量规的 3 星），清题、游标 +1、按顺序推进下一知识点出新题；判错：不降星不换点，题标记 `hint_given`，转入针对错误的追问；追问/求助/意愿类不进判答（七分类优先级：结束 > 改时间 > 自评 > 选点 > 追问 > 求助 > 答题）。
- 出题/判答事件：新题出现记 `tutoring_question`（kp、题干、提示标记），判出结果记 `tutoring_answer`（verdict、hint_given、stars_after）。平台会话进 `learning_events`，demo 态（STUDENT_DEMO_MODE=true）走同一份 `record_event` 落 runtime JSON；独立态不落盘（事件随会话 state 在 runtime/sessions 可追溯）。
- 判对的证据条目走既有 `mastery_updates` 通道（evidence="辅导检测题答对（有提示/无提示独立作答）"、source="tutoring"），平台态由会话层写 `knowledge_mastery`（星级只升不降）。
- 自评存储：迁移 `final07` 给 `student.knowledge_mastery` 加 `self_rating` 列；`upsert_self_rating` 只写自评列不动星级（demo 态读-改-写，与掌握度互不冲掉）；`read_self_ratings` 平台态读取；server `_step` 按会话增量同步自评。
- `/state` 的 tutoring 块新增 `question`（kp_no/text/hint_given）与 `stars`（编号→系统星级）；掌握条渲染「系统 n★」+「自评 n★」。

**测试结果**

- 缝 A：`apps.test_post_video_tutoring` 扩到 24 用例（出题、判对升星推进、判错标记提示不降星、非作答不动状态、demo 事件落盘）。连同 `apps.test_api_integration` 共 53 全过。
- 缝 B：`SelfRatingPersistenceTest`（demo 读写 + 掌握写入不冲自评）过。平台 SQL 路径无库未测，靠评审（幂等键、GREATEST 保星、COALESCE 不覆盖）。
- 组件：掌握条星级断言更新后过；前端已重建发布。e2e 2 过。

**演示路径（本地 8088）**

进辅导后随便说一句（如「准备好了」）→ AI 出第一题「小检测……」；接入模型的部署里答对升星、答错追问；掌握条出现「系统 1★」。demo 事件在 `student_agent/runtime/integration/events-<sid>.json` 可查。

**给后续票的注意事项**

- 票 04：`tutoring_question` 的 `question` 字段即题干摘要（digest），出题事件已按 `(session_key, event_type, event_id)` 幂等落 `learning_events`——查已见清单直接按 `event_type='tutoring_question'` 查 payload.question；「确认题」出新题时把已见题干列表喂给出题 prompt 避开。5 星门槛挂在判对升星处（`min(5, current + 1)` 的 no-hint 分支前加校验）。
- 票 05：结束时 `tutoring_question` 若还挂着，反馈里应体现「未完成的检测」；`mastery_updates` 累积的 evidence 列表可直接进反馈的星级依据区。
- 量规的 3 星封顶目前硬编码在判对分支，票 04 配置文件落地时改为读量规。
