# Design / procedural live audit — 2026-11-10

使用 Matt `diagnosing-bugs` 的真实调用反馈闭环，以及 `codebase-design` 的 interface-is-test-surface 原则；经当前 `service.start_discussion` / `service.classroom_turn` 调用正式 teaching agent、工具与逐项状态更新。没有改产品代码、没有写生产数据库。当前任务仅诊断，不执行 skill 的修复阶段。

## 素材与方法

真实课程归档：`student_agent/docs/knowledge-extraction/validation/2026-11-05-live-model/knowledge-points.json`。课程 ID `02b49c92-5d63-47bc-9295-2300b7f69203`，lesson `-EXmpqbyvKbisC`；本组使用“设计并验证合法出栈序列”“设计行编辑整行撤销的栈方案”两个 design 点，保留全部原始 rubric。素材是已有真实课程的提取结果，本轮没有重新提取，也没有访问在线课程。没有找到第二门真实数学/代码课程，因此不声称跨学科覆盖。

真实教师模型 `deepseek-v4-flash`；主批 20 次成功模型请求，复跑 3 次，共 23 次（6 次开场 + 7 次学生输入产生14次评估/回复，复跑1次开场+1次学生输入）。学生答案为开发者固定输入，便于复现，不能代表真人学习效果。

复跑命令（仓库根目录 PowerShell）：

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe student_agent/evidence/new-knowledge-audit-2026-11-10/procedural/runner.py
# 独立复跑：用新的 AUDIT_RUN 名称避免覆盖证据
$env:AUDIT_CASE='illegal-empty-pop'
$env:AUDIT_RUN='repeat-2'
.venv/Scripts/python.exe student_agent/evidence/new-knowledge-audit-2026-11-10/procedural/runner.py
```

完整调用输入、模型输出、toolCalls、usage、逐轮状态见 `run.json` 与 `repeat/run.json`；不含凭据。

| 场景 | 预期 | 实际 |
|---|---|---|
| valid-alternative：直接置top=-1而非循环Pop，完整实例 | mastered | mastered |
| partial-then-complete：只答push/@后补齐#、实现及实例 | 首轮partial，补齐mastered | 一致 |
| wrong-single-pop：把@当成退格 | 不掌握 | misconception |
| prerequisite-missing：不懂1/0和栈顶，请演示一步 | 不掌握、解释先修 | partial，解释并示范第一步 |
| correct-step-derivation：110100逐步推演BCA，解释CAB不可能 | mastered | mastered |
| illegal-empty-pop：第一步空栈Pop，且带入D | 不掌握、指出具体非法操作 | misconception，指出两错 |

主要判定6/6符合预期。这不是教学质量满分；逐项记录和回复仍有以下问题。

## 已复现问题：未考查内容被记录成“还需帮助”

`illegal-empty-pop` 开场只请学生设计操作序列、逐步模拟、输出结果，没有要求判断任何不可能出栈序列。学生确实犯了空栈Pop错误，但没有讨论“不可能序列”。第一次运行 successCriteria:3 保持 unconfirmed；相同输入复跑却变为 needs_help，evidence 精确为“学生未讨论任何不可能序列。”，gap 为“未指出违反LIFO的具体步骤。”。

这同时说明：

- 未提到/未问到会被当成“不会”，违背最新版方案“未提及的要求不更新”“没问到不等于不会”。
- 同一场景同一模型同一rubric，该项状态由 unconfirmed 变为 needs_help，逐项证据稳定性不足。
- 两轮都将 successCriteria:2 因“未给出出栈序列”直接记 needs_help。这里原题确实要求输出，合理性强于上例，不能与从未询问的不可能序列混为一谈。

建议优先约束工具：缺少表达应与错误证据分开；对未考查要求，仅凭“未讨论/未说明”不得写 needs_help。进一步回归需要对“本题涉及哪些项”建立约束。这是测试观察下的修复方向，未实施。

## 次要观察：帮助过宽，减少学生自行构造空间

partial-then-complete 第一轮学生仅答“普通字符push，@清空”，教师一次给出三种操作完整规则、循环Pop/置空实现、完整串ab#c@d的逐步结果，再让学生换串。illegal-empty-pop 也在指出第一步错误后完整给出110100/BCA全套答案。评估能拒绝错误，却倾向将整题答案一次性示范，较难检验后续是否真正迁移。此为人工教学质量观察，不能仅凭这两个样本断言所有帮助都过度。

## 范围限制

本组只覆盖 design 两个点、6种输入情境，短对话7轮+复跑1轮，没有测试首轮5/补强8上限、课后恢复、认证HTTP命令、持久化与前端。直接调用真实服务interface并保留完整state，不能代称端到端测试。没有数学独立课程、真实代码执行器或真人学生；栈推演属于算法过程而非完整数学推导验证。
