# 逐项证据规则修正与真实模型复测

2026-11-11。按 Matt diagnosing-bugs 先复现，再最小修改；codebase-design 采用现有教学调用者接口，不另写评估提示词替代产品。

## 修改范围

仅修改 typed_teaching.SCOPED_PROMPT：未提及、噪声、纯提问、含糊确认不提交对应项更新；明确不会、具体错误或实际尝试未完成才记 needs_help；保留无依据项原状态；已确认项仅有相反证据才降级。混合作答仍可评估实际答案，一答仍可覆盖多个要求。不增加证据类型、状态字段或程序语义校验；不改选点、轮数和掌握规则。同步更新实现文档。

## 真实模型闭环

真实模型 deepseek-v4-flash，使用11月10日真实栈队列课程归档状态，人工固定学生输入。通过当前 typed_teaching.run 执行实际 Agent、工具评估、状态更新和回复；不使用生产数据库、HTTP或浏览器。保留完整前后状态、实际回复及assessment_history中的模型工具提交。无凭据写入。

1. 修改前：重放 noise 和 illegal-empty-pop 各2次，4次中3次失败。噪声两次均写缺口；design未询问的“不可能出栈序列”一次保持未确认、一次误写缺口。见 baseline.json。
2. 初次修正后：8场景各2次。after.json中标记14/16通过；其中两次所谓失败是测试预期错误——旧归档partial输入只描述队列基础定义，并没有尝试假溢出要求，应该保留未确认。实际模型正确保留。原始证据未覆盖或改写。
3. 修正该测试预期，另加真正尝试未完成、相反证据和正确等价表达对照。最终11场景各2次，**22/22符合限定判据**，见 verified.json。

| 场景 | 两次结果 |
| --- | --- |
| 噪声 | 所有要求原状态不变 |
| 单纯懂了 | 所有要求原状态不变 |
| 纯提问 | 所有要求原状态不变 |
| 未涉及当前要求的队列定义 | 所有要求原状态不变 |
| 明确不会 | 当前要求needs_help，其余要求原状态不变 |
| 假溢出具体错误 | 当前要求needs_help，其余要求原状态不变 |
| 实际尝试假溢出但解释不完整 | 当前要求needs_help，其余要求原状态不变 |
| 非法空栈Pop | 仍记录实际错误；未考查的不可能序列要求保持unconfirmed |
| 已有掌握后仅提问 | 各项状态及原有证据均保留 |
| 新回答推翻已有队空理解 | 对应原demonstrated项改needs_help |
| 完整等价记忆答案 | 正常整点mastered |

## 复跑

仓库根目录 PowerShell：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:AUDIT_CASES=''
$env:AUDIT_REPEAT='2'
$env:AUDIT_OUTPUT='student_agent/evidence/requirement-evidence-2026-11-11/recheck.json'
.venv/Scripts/python.exe student_agent/evidence/requirement-evidence-2026-11-11/runner.py
```

runner读取11月10日evidence归档及本机已有模型环境配置；复跑使用新输出名称，避免覆盖原始记录。它检查实际状态而非提示词文字。其他既有测试命令：`.venv/Scripts/python.exe -m pytest student_agent/backend/tests/test_typed_teaching.py student_agent/backend/tests/test_typed_teaching_commands.py -q`，16 passed、24 skipped（未配置隔离测试数据库）。

## 解释边界

通过的是这11类输入的指定证据规则，不是所有教学质量。design整题实际尝试中的缺失仍可能记needs_help，但完全未考查的不可能序列保持未确认。两次重复不构成统计稳定性保证；单课程、单模型、固定人工学生，未来仍可能出现语义误判。没有声称HTTP/持久化或跨学科验收通过。未自动增加证据字段，未提交或部署。
