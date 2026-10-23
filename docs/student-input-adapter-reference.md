# 学生端输入适配：开发字段参考

> 核查依据：2026-10-22工作区代码，包含按所选课时隔离上下文的本地实现，不代表已部署。
> 阅读主流程请先看[机制文档第3章](student-runtime-mechanism.md)。本文保留查代码时需要的嵌套字段、固定配置和数值示例；知识点文件格式单独见[教师端对接约定](student-knowledge-point-contract.md)。

## 1. 转换函数的输入

`load_plan_for_session(state)` 接收会话状态，主要读取两个字段：

- `state.learning_context`：仅含选中课时正文的内部 `CourseLearningContext`，附有课程身份、发布版本和全课目录摘要。
- `state.lesson_id`：必须与上下文 `selected_lesson_id` 及唯一课时匹配；缺失或不一致直接报错，不回退到其他课时。

转换分两步完成：平台JSON先由 `from_platform_payload` 转为内部模型，再由 `load_plan_for_session` 生成计划。前一步已把课堂场景的 `speech` 动作合并成段落正文；后一步使用这些段落，不再次解析教师原始文件。两步均由程序执行，不调用LLM。缺少学习上下文时返回 `None`，开课流程据此拒绝开课。

知识点在平台按所选课时的文件提取，学生端核对返回的 `selectedLessonId`，再构造内部 `evaluation.knowledge_points`。无匹配文件时保留空目录，不借用其他课时的唯一文件。未选课时时上下文只含目录摘要，不允许生成计划或开课。

平台请求为 `{"launch_token":"…","lesson_id":"L2"}`。响应中 `selectedLessonId=L2`，`lessons` 只有L2，`lessonCatalog` 可含L1、L2的标题、周次、学时和场景数，不能含正文。材料须明确归属L2，或为无课时绑定的课程共享材料；无归属材料排除。

内部结果以普通字典写入 `SESSIONS[sid]["state"]["learning_context"]`，会话包装层保留副本，每轮传给LangGraph；完整state保存为 `student_agent/runtime/sessions/<sid>.json`。未使用LangGraph checkpointer。旧会话的计划课时或发布版本不一致时返回409，另建会话，不覆盖旧记录。

## 2. 计划字段参考

函数返回一个字典，开课校验通过后存入会话的 `lesson_plan`。它描述本节课的内容与流程配置，学生回答、当前进度和星级另存于运行状态。

| 计划输出字段 | 从哪里来／怎么生成 | 在哪里使用 |
| --- | --- | --- |
| `version=2` | 程序固定值 | 标记内部计划格式；与平台的 `schemaVersion=1`、课程发布版本是三个不同概念 |
| `source=platform-published` | 程序固定值 | 提示词辅助模块判断是否使用平台课程内容 |
| `publication_id / publication_version` | 上下文 `publication.id / version` | 标记计划依据的发布版本；生成教学上下文、校验旧空目录修复的版本归属 |
| `course_id` | 上下文课程ID | 标记课程归属，辅助同课程校验 |
| `lesson_id` | 已校验的所选课时ID | 标记计划对应课时，校验恢复与目录修复归属 |
| `lesson_title / title` | 所选课时标题 | 开场、课堂展示、学情报告、教学提示词中的课时名称 |
| `total_minutes` | `max(20, 5 × 段落数)`，单位分钟 | 计划校验、计划时长展示及阶段预算；是程序估算，不直接使用教师填写的 `teaching_hours`，也不是视频真实时长 |
| `stages[]` | 程序生成讲解、复述讨论、深入探究三项配置 | 开课时读取启用阶段、预算及交付方式；启用课后辅导开关时，实际阶段序列将后两个阶段替换为 `tutoring` |
| `segments[]` | 选中课时的内部段落 | 保存课件页标题、讲稿正文及场景来源；供教学内容定位、提示词和段落推进使用 |
| `knowledge_points[]` | 上下文评价知识点，转换字段名称 | 辅导目录、出题、判答、不会时讲解，以及评分证据的知识点归属 |
| `knowledge_sources[]` | 已发布材料条目的内部表示 | `prompt_context.lesson_sources` 选择相关正文，作为教学提示词的材料依据；不是每次全量发送 |
| `evaluation` | 内部评价模型整体转为字典 | 随计划保留评价内容与来源标记；专用辅导出题、判答直接读取上面的 `knowledge_points[].expected` |
| `advance_policy` | 程序固定推进配置 | 开课时装入流程状态，用于阶段预算和证据推进；不代替课后辅导的答题、跳过等专项逻辑 |

其中几个数组的内部字段如下：

| 对象 | 内部字段及用途 |
| --- | --- |
| `segments[]` | `id`：内部段落标识；`title`：页／段名称；`order`：顺序；`content`：讲稿或材料正文；`knowledge_point_ids`：与本段文字匹配的知识点ID；`source.scene_id`：原课件场景ID；`source.position`：来源位置描述 |
| `knowledge_points[]` | `id`：题目、证据与记录的关联标识；`title`：名称；`expected`：出题和判答的应会内容；`misconceptions`：兼容的误解内容，当前知识点Markdown解析器不生成，通常为空 |
| `knowledge_sources[]` | `id / title / content / source_name`：材料标识、标题、正文、首条引用的来源名称；地址不自动转成正文，空正文无法提供实质教学依据 |
| `stages[]` | `id / name`：阶段标识和名称；`enabled`：是否启用；`minutes`：预算；`advance_when`：推进条件；讲解阶段另有 `delivery=video` |
| `advance_policy` | `on_budget_exhausted=advance`、`on_evidence_reached=advance`、`min_stage_minutes=0`、`max_stage_overrun_minutes=10`，均由程序提供 |

`segments[].knowledge_point_ids` 当前按完整知识点名称或某条完整应会内容是否出现在段落标题／正文中进行匹配，匹配前转小写。只有一个段落且完全未匹配时，关联全部知识点；多个段落中没有匹配的段落会保留空关联。这不是LLM语义识别，也不保证每页都关联到知识点。

## 3. 转换示例

假设选中的第1课时有5个课件场景，学习上下文评价中有3个知识点：

```text
输入：内部学习上下文 + 选中的课时ID
  课时：第1周
  场景：5页，每页有标题、场景ID及讲稿
  知识点：3项，每项有ID、名称及应会内容
  发布版本：pub-example / 1

输出：lesson_plan
  lesson_title：第1周
  publication_id / publication_version：pub-example / 1
  segments：5项，保留每页讲稿、来源和匹配的知识点ID
  knowledge_points：3项，expected_concepts 改名为 expected
  knowledge_sources：已发布材料正文
  total_minutes：25
  stages：讲解12分钟、复述讨论6分钟、深入探究6分钟
  advance_policy：程序固定推进配置
```

阶段预算采用整数除法，因此示例中合计24分钟，不保证与总时长25分钟完全相等。开课启用课后辅导时，实际阶段序列为讲解后进入辅导，辅导有独立的时间安排；不能把这里保留的旧阶段预算当成辅导倒计时。

播放器地址仍从学习上下文的课时课堂读取，未复制为上述计划的顶层字段。`user_id` 同样保留在身份／会话上下文中，不靠教学计划确定学生身份。

## 4. 知识点接入修复记录

2026-10-21核查“现代交换原理”第1周时，知识点正文已有内容，但桥接遗漏课时文件类型，且旧解析器将细目合并为总标题。修复补齐资源类型转发与末级标题解析，见[PR #28](https://github.com/huanche/agentic-class-pilot/pull/28)。当时服务器版本为 `a7b3e26`，实测返回9个知识点；该版本号是当次验证记录，不代表当前部署版本。

旧空目录会话重入时，仅在课程、课时、发布ID和版本一致的情况下补齐知识点、评价要点及段落关联，保留原课件、计时、消息、星级和统计，清除旧空目录生成的无归属检测题。已有非空目录不自动重排，跨课时或跨发布版不迁移。实现见 `course_adapter.py::repair_empty_knowledge_catalog`。
