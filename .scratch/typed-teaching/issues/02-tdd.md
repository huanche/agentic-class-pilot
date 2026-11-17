# 教学流程 TDD

Status: resolved

已确认的测试入口：学习命令 HTTP 接口和学生页面。每次一条失败测试，再做最小修复；已有通过测试不声称是 TDD。

- [x] 页面退出竞态。
- [x] 命令接口保存、恢复及失败重试。
- [x] 相关回归和结果记录。

## Answer

两个入口各一条行为测试：先复现失败，再做最小修复，通过后进入下一切片。后端相关42、前端unit42、浏览器21与构建通过。见[实施记录](../../../student_agent/docs/knowledge-teaching/implementation.md)。
