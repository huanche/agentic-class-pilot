# 真实模型边界测试

模型：deepseek-v4-flash。原批次42次模型请求，重跑6次，共48次。20次学生输入（12独立分叉＋8连续不会），重跑3次，另1次真实开场。没有数据库、HTTP或生产写入；学生输入为人工编排的边界刺激，导师调用是真实供应商。

素材：student_agent/docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json 的“循环队列与假溢出的解决”。来源标识：{"courseId": "02b49c92-5d63-47bc-9295-2300b7f69203", "lessonId": "-EXmpqbyvKbisC", "sourceRevision": "96d3825f111bfaeb822b71747b73dd0fdc5a53acdf456a9a1d6709d667e914e0"}

按 Matt diagnosing-bugs 建立 service.start_discussion/classroom_turn 可复跑反馈闭环，codebase-design 使用现有 session Interface，不另写提示词替代真实方案。此次为诊断测试，不改产品，未执行修复阶段。GLOSSARY.md、docs/adr不存在；已读AGENTS，backend无更深AGENTS/CLAUDE。

## 发现

1. **高：缺少知识表现仍写入needs_help，而且不稳定。** 首轮噪声、懂了和提问分别表现为needs_help/needs_help/保持unconfirmed；重跑分别为needs_help/保持unconfirmed/needs_help。噪声2/2复现，懂了1/2、提问1/2。工具证据明确使用“未作答，仅输入无意义字符”“尚未说明…只提出疑问”，属于未确认被升级成缺口，而非观察到了错误理解。当前被问的是understandingPoints:1，其他未被问要求均保留unconfirmed；不能夸大为全要求乱改。局部needs_help误标会影响缺口反馈和后续补强。

2. **中：连续不会仍重复相同讲解，甚至与自述矛盾。** 第4/6/8轮重复8格数组、front3 rear8和同一句因果总结；第6轮说“不用你回答”后又要求回答空或满。第7轮称“彻底换一种方式”，却给出另一张格子图并直接附答案。第8轮说“这个点先放一放”并引向绕回0，但实际state仍处reinforce、首要求needs_help。是可见文案与程序焦点不一致，未达到掌握误判。

3. **中/需人工判断：课程示例绑定过强。** correct_full解释了假溢出机制、取模和空满条件，第一要求仍因未点名front3 rear8及0~2被判needs_help；第五项确实未答“一般状态”，保留缺口合理。第一项本身是具体示例，因此需决定示例数字是否必要验收标准，不能直接宣称模型错误。

4. **正向：** 注入指令未把要求标demonstrated，答非所问保持未确认；正确综合答案一次确认取模/队空/队满三项；真实开场attempts=0，无学生评估；连续第5答转reinforce，8答后recall5/reinforce3，尚未跑满补强8轮，不能宣称13轮上限验收。

## 每例实际结果

| 场景 | 状态变化 |
|---|---|
|unknown|understandingPoints:1:needs_help|
|wrong|understandingPoints:1:needs_help|
|partial|understandingPoints:1:needs_help|
|off_topic|未新增要求证据|
|question|未新增要求证据|
|empty|未新增要求证据|
|noise|understandingPoints:1:needs_help|
|understood|understandingPoints:1:needs_help|
|injection|未新增要求证据|
|mixed|understandingPoints:1:needs_help, understandingPoints:2:needs_help|
|context_missing|understandingPoints:1:needs_help|
|correct_full|understandingPoints:1:needs_help, understandingPoints:2:demonstrated, understandingPoints:3:demonstrated, understandingPoints:4:demonstrated, understandingPoints:5:needs_help|
|repeated_unknown_1|understandingPoints:1:needs_help|
|repeated_unknown_2|understandingPoints:1:needs_help|
|repeated_unknown_3|understandingPoints:1:needs_help|
|repeated_unknown_4|understandingPoints:1:needs_help|
|repeated_unknown_5|understandingPoints:1:needs_help|
|repeated_unknown_6|understandingPoints:1:needs_help|
|repeated_unknown_7|understandingPoints:1:needs_help|
|repeated_unknown_8|understandingPoints:1:needs_help|

## 重现与限制

仓库根执行 `.venv/Scripts/python.exe student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/runner.py`；重跑 `.venv/Scripts/python.exe student_agent/evidence/new-knowledge-audit-2026-11-10/boundary/replay.py`。脚本会覆盖本目录证据，正式复跑请先复制到新输出目录。run.json/replay/run.json保存每次实际模型消息、工具参数、usage、前后状态和自然回复，不保存凭据。

所有结论均为单一真实课程concept点、单模型小样本；未覆盖HTTP空输入校验、并发提交/幂等、数据库提交回滚、真实学生学习效果、跨课程推广。空白能穿过service seam不等于HTTP产品漏洞。未修复任何产品问题。

## 增量：完整5+8与课后续学

在原8轮真实状态后恢复内存session，独立保存 continuation/run.json；没有数据库持久化或HTTP恢复验证。执行 continue.py 增加5次学生回答，另finish（无模型）、真实课后开场及1次课后回答，共13次额外模型请求。**本组最终共61次真实模型请求**；原20次学生输入＋3次重跑＋5次限额续测＋1次课后回答=29次学生输入，另原开场和课后开场各1次。

- **高优先级教学质量问题：第9/10/11/12轮回复逐字相同。** 已做字符串相等断言。均说“你已经知道rear撞墙、前面还有空位”，但学生全程只说不知道，没有证明这些认识。首要求仍needs_help，程序没有虚假确认；这是自然语言虚构学生已知和反复追问。4轮都以相同rear7绕回0计算题结束。
- 第13答真实完成wrapup，程序recall_attempts=5、reinforce_attempts=8。总结没有再出题，没有宣称全部掌握；具体将后续空满等称为“还没确认”，保留了未确认和缺口区别。
- finish后真实课后开场重新给出最初front3 rear8的问题；一次“还是不知道”后转讲取模并问rear5。说明service内存轨迹可以续学；不等于验证数据库保存恢复。课后是否过度重头考需要进一步评估，不能把旧题再现本身当成错误。

增量断言命令检查wrapup、5/8计数和四轮回复完全相同，均通过。没有测试学生提前退出再恢复，该覆盖仍空缺。
