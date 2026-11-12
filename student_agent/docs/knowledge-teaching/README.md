# 结构化知识点的教学使用

本目录独立维护学生端使用结构化知识点开展教学的方案和实施记录，已在本工作树实现，未部署。

## 本次收尾记录

本次学生端文档统一放在 `student_agent/docs`，原始测试证据统一放在 `student_agent/evidence`。以下结果是有限样例验证，不代表模型语义判断可以得到普遍保证。

- [复合项证据与重复帮助修复](../../evidence/compound-help-fix/REPORT.md)：75项回归和最终7项真实模型测试通过，保留失败版本。
- [首次出题避免泄露解法](../../evidence/design-task-live/REPORT.md)与[退出续学组合验证](../../evidence/design-task-live/COMBINED-20261111.md)。
- [数组PPT完整HTTP链路实测](../../evidence/arrays-e2e-2026-11-11/REPORT.md)：上传、生成发布、学生学习及恢复，未完成浏览器播放验收。
- [三子Agent剩余风险验证汇总](../../evidence/teaching-risk-review-20261111/REPORT.md)：修复前的复合项与5/8轮验证。
- [本次过程记录](records/2026-11-12-progress.md)。
- [文档归位与剩余验证收尾](records/2026-11-12-document-relocation.md)。

## 历史方案与验证

- [教学方案](plan.md)：先读这份，说明怎么教一轮、什么时候换点和结束。
- [本问与整点分开：实施验证](validation/2026-11-10-requirement-progress/README.md)：逐项证据、程序汇总、TDD回归与仍未解决的复合项宽判。
- [实施记录](implementation.md)：实际改动、验证结果及限制。
- [掌握与缺口一致性修复记录（已回退）](mastery-gap-fix.md)：保留历史实施说明，当前不生效。
- [真实课时与模型实测](validation/2026-11-06-live-model/README.md)：三种提问、补强与反馈的实际对话，及仍需改进的地方。
- [重复追问与切点修复](validation/2026-11-06-reply-fixes/README.md)：原因、改动和真实模型回放。
- [动态模拟学生重跑](validation/2026-11-10-responsive-student/README.md)：学生根据最新提问与提示回答，检查修复后的追问和切点。
- [多子Agent困难场景](validation/2026-11-10-multi-scenario/README.md)：12个有效会话，含误解、含糊、跑题、质疑、跳过请求、恢复和故障重试，保留自然失败。
- [实现细节（备查）](implementation-notes.md)：字段、工具参数和代码位置，实施时再看。
- [上游知识点提取](../knowledge-extraction/README.md)：已基本完成的结构化协议、提取、保存、字段传递及其验证记录；与本目录分开维护。

旧会话保持原教学方式，新建的三类型知识点会话使用新流程。
