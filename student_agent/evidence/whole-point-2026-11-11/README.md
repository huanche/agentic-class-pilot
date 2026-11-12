# 整点提问、累计评估与提取去重验证

2026-11-11。使用Matt codebase-design的既有调用者接口原则；沿用本地真实模型反馈闭环。此次包含此前尚未提交的截图问题修正，未提交或部署。

## 实现

- typed_state.teaching_plan：提供当前点全部未完成要求为计划覆盖范围，真实needs_help优先；不再固定只问第一项。首次ask组织整点任务；未确认项不因曾列入计划就直接被当作缺口讲解。后续按实际表现选ask/clarify/explain/correct，纯提问先答疑。选点、5/8轮及掌握汇总均不改。
- typed_teaching：三类型按整体事实、核心关系、完整构造组织主任务；一答可覆盖多项，补问只针对未完成内容。为已有动作提供生成约束，ask不预先讲答案，explain/correct不顺带讲完所有未考查内容；memory不额外考因果或推演。若非主动求助，补完当前卡点后可转问尚未涉及内容，不复述刚讲内容。主动提问／请求直接讲解时可以只答疑。
- 生成阶段隐藏评估模型的next_step建议，保留它在学习记录中；实际生成由程序计划决定。否则评估中的“讲完再让学生重述”会与新规则冲突。仍提供本点实际对话、已会与缺口。
- content.prompts：合并同义关系、重复小结、样例复述门槛；保留独立事实与能力，不设条数上限；禁止再添加把独立目标捆绑回去的综合验收项。不改变内容schema，不自动合并已发布知识点。

无新增数据库字段／模型调用阶段；计划范围不是已经实际考查的证明，更不能直接作为学生表现。

## 教学实测

真实deepseek-v4-flash，真实归档栈队列课程，固定人工学生输入，调用typed_teaching.run，不写业务库。原知识点未经精简，用于分离教学策略与提取变化的影响。

teaching*.json保留历次输出。第一批虽然完成判定正常，但部分回答后仍先讲完所有答案再让学生复述；后续加入具体动作约束，又定位到评估next_step冲突，没有将这些中间结果算作全部通过。

最终材料：

- teaching-verified.json：三类型完整答案均一次mastered；design使用归档ABC实际任务与对应答案配对，新生成的设计开场另作问法观察，不能把不同题目的答案当作正确作答。
- teaching-focused-2.json：memory部分回答后仅补栈底卡点，再问尚未涉及的Push/Pop及进出规律，没有先给出后面答案或要求复述栈底。补全后mastered；概念直接求助得到解释，未被误判掌握，没有追问复述。
- teaching-help-final.json：最终答疑约束下再次测试明确求助，仅回答问题，不追加考试。
- screenshot-replay.json：此前截图多轮累计回答被合并认可；达到第5轮仍求助时先解释再换点；只有LIFO/FIFO术语而无其他依据的对照没有放行。

主任务仍可能包含相关的多个表达方面；本次不是把每轮机械限制为一个问号。也不保证每位学生5轮内掌握。

## 提取实测与比较

同一真实材料用修改前提示词独立提取：extraction-before.json为13点54项。中间版extraction-after.json为11点47项，但独立目标回归出现误合并，未当作最终成功。

最终prompt的四个真实提取检查全部通过，原始记录在：

`student_agent/docs/knowledge-extraction/validation/2026-11-10-requirement-splitting/whole-point-20261111-2/`

- 独立HTTP事实保持分开。
- 留空位区分空满的完整因果关系保留。
- 设计的单字符退格与整行撤销分别记录，没有重复总验收项。
- 真实课时链队列插入规则和容量限制保持独立。

最终真实课时样本为13点50项，重复的末尾“栈与队列对比”不再单独成点，其他独立主题仍可能单列。数量减少不是验收指标；此次单次新旧对比不证明每次提取都减少4项或完全无重复。不同类型的事实、因果和实作仍需人工抽查。

## 自动化验证与边界

命令：`.venv/Scripts/python.exe -m pytest student_agent/backend/tests/test_typed_teaching.py student_agent/backend/tests/test_typed_teaching_commands.py student_agent/backend/tests/test_typed_knowledge.py student_agent/backend/tests/test_extraction_requirements_live.py -q`

49 passed、28 skipped（24项需要独立数据库、4项真实模型测试默认需显式启用；后者已单独启用执行并4 passed）。新增测试通过实际Agent调用检查整点覆盖不生成证据、答多项后仅剩缺口、忽略评估中错误的复述建议、纯提问只选解释且不新增掌握。

未覆盖浏览器完整学习流程、跨学科、真人学习效果或所有模型。已有用户课程、发布内容、会话和掌握判定没有自动覆盖。新的提取规则仅在后续实际提取时生效。
