# 概念/事实真实模型测试

2026-11-10；调用当前工作树 service.new_dialogue/start_discussion/classroom_turn。使用 Matt diagnosing-bugs 的可重跑反馈循环和 codebase-design 的调用者同接口测试原则。无产品修改、无生产写入。学生回答为明确标注的固定测试输入，教师评估和回复均为真实模型，不冒充真人学生。

## 范围与来源

真实课程：归档栈与队列课程，来源 student_agent/docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json；课程原始教学文本可对照 student_agent/docs/knowledge-teaching/validation/2026-11-10-multi-scenario/source-excerpts.json。使用其中“栈与队列的定义及 LIFO/FIFO 规则”“循环队列与假溢出的解决”。来源元数据与代码SHA见run.json。模型 deepseek-v4-flash。6场景8轮学生输入，另1场景1轮复跑；总26次实际请求（含开场/评估tool/自然回复）。不是HTTP鉴权或数据库全链路测试。

## 结果

| 场景 | 判据 | 实际 |
|---|---|---|
| memory-equivalent | 完整等价表述可一次涵盖多项 | 5项demonstrated并掌握，通过 |
| memory-incomplete | 只答LIFO/FIFO不能整点掌握 | partial，位置/操作受限项保留，通过 |
| memory-confusion | 颠倒栈队列应识别误解 | 4项needs_help，纠正，通过 |
| concept-conclusion-only | 只说“用循环队列解决”不代表理解 | 首项needs_help，其余unconfirmed，通过 |
| concept-causal | 接受解释关系，不强制复述数字，未说一般状态保留缺口 | 首轮和复跑均以没说front=3/rear=8具体数字拒绝第一项，存在过度拘泥样例问题 |
| concept-repetition | 连续无进展应换方式/澄清卡点 | 3次继续解释同一0~2空位与rear=8关系；第三次虽拆小问题，仍缺少“没看懂题还是不会表达”的明确澄清，部分改善但帮助较重复 |

## 确认问题

1. **P1 教学回复算错插入位置（单次发生、复跑未复现同一算错）**：concept-causal原始回复：“下次入队位置是 `(8 + 1) % 8 = 1`，从而复用前端的空位。”源课程定义rear指向下一插入空位；将顺序rear=8归一化应为0，不能跳到1。复跑转而写`(7+1)%8=0`，但未澄清rear语义变化。源提取条目本身把“下一次入队位置”写作(rear+1)%，与rear下一空位定义存在语义隐患，真实教学会放大它。观察：1/2场景运行出现明确错误，不可当作统计错误率。
2. **P2 掌握判断过度依赖例题数字（2/2运行）**：学生已解释“前部有空位、rear到末端报满、取模复用空间”，两次仍拒绝假溢出关系项，gap明确要求front=3/rear=8/0~2，与“不要求复述样例全部数字”冲突。复跑连“front和rear按容量取模移动”也被以没写显式公式拒绝。未提及“一般状态”仍需帮助是合理缺口，不能把整个partial都判错。
3. **P2 完成总结擅加课程外待巩固项**：memory-equivalent全部5项掌握后，回复另外称“接下来值得自己巩固：把LIFO/FIFO和具体操作过程联系……给定入栈/入队顺序推导出栈/出队顺序”。本场只含记忆点，未测试该能力；可作为可选建议，但不宜暗示是已诊断的缺口。

## 复现

初次：`.venv/Scripts/python.exe student_agent/evidence/new-knowledge-audit-2026-11-10/conceptual/runner.py`。复跑：设环境AUDIT_CASE=concept-causal、AUDIT_OUTPUT=rerun-causal.json，再执行同命令。run.json和rerun-causal.json包含完整脱敏模型消息、tool调用、usage、开场/学生输入/回复、每项进度前后快照。报告未执行修复，技能修复/回归变绿阶段不适用。
