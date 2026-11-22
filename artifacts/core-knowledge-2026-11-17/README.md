# 核心知识点提取改造

使用 Matt Pocock codebase-design 技能，按提取模块 Interface 集中处理格式校验、修复、去重和身份生成。

## 同步修改

| 位置 | 修改 |
| --- | --- |
| 提示词与工具 | 输入 course_name/materials；工具只接受 name/explanation；数量 1–3；拒绝类型和额外字段 |
| 课程名称 | 平台从 Course.title 读取，通过 courseName 随发布请求传入；直接准备从 context.courseTitle 传入 |
| 发布队列 | 课程名保存在已有 coverage 元数据；旧任务收到课程名后可补齐并重新准备；无需新增数据库字段 |
| 提取结果 | 模型只生成两个字段；程序生成 ID，并派生 title/content/description，供现有界面和提问使用 |
| 内容版本 | 新结果使用 schemaVersion=3；保留历史 v1/v2 校验；新提取器缓存与旧内容版本分离 |
| 后续提问 | 新结果进入现有无类型提问、评估、反馈流程；旧三类型会话保持原流程 |
| 动态教学 | 可选动态流程支持从 explanation 读取知识依据，不编造来源引用 |
| 测试与客户端 | 更新协议测试、调用方参数、历史兼容测试和生成客户端，增加发布落库、恢复及实际启动验证 |

## 文件说明

- `知识点结果.md`：便于直接阅读的真实模型提取结果。
- `knowledge-points.json`：仅含 name/explanation 的提取结果。
- `input.json`：程序从归档资料读取的课程名称和本课材料，不含账号数据。
- `prompt.txt` / `tool-schema.json`：本次使用的提示词与工具结构。
- `extraction-report.json`：程序编译后的结果、调用和修复次数。
- `teaching-smoke.json`：两轮模拟学生输入、真实导师回复和评估。
- `feedback.json`：上述模拟会话结束时的反馈，不代表真实学生表现。
- `lesson-content.json`：通过校验的 v3 内容包。
- `startup-smoke.json`：真实 Uvicorn 进程启动后的健康检查和前端页面 HTTP 结果。
- `validation-summary.json` / `backend-database-test.log`：验证范围和后端完整测试记录。
- `changes.patch` / `source/`：本次代码差异与新增验证入口、测试；不包含密钥或环境文件。

## 运行说明

复跑真实模型验收：

```powershell
./student_agent/.venv/Scripts/python.exe student_agent/scripts/verify_core_extraction.py --output artifacts/core-knowledge-review-new
```

该脚本只读取本机已有模型配置用于调用，不导出配置或写业务数据库。后端数据库专项测试使用独立的一次性 PostgreSQL；不连接现有课程数据库。

发布时须一起更新平台课程名传入、学生端协议和对应生成客户端。旧任务缺课程名时，需要通过平台正常重新登记该课时以补齐；不要用课程 ID 伪造名称。旧学习会话仍使用固定的原内容版本。

本次未部署线上；验收课程是归档的“一维数组”课时，不能据此保证所有课程的语义提取质量。当前提问复用了已有无类型流程，未新建逐目标掌握追踪模型。

## 本次验证结果

- 学生后端完整回归（独立 PostgreSQL）：347 通过、19 跳过。跳过项为需要额外启用的真实模型专项场景。
- 前端单元测试：42 通过。
- 浏览器端到端测试：26 通过；前端生产构建成功。
- 平台课程名传入适配测试：4 通过。
- 契约与客户端相关测试：27 通过、146 子测试通过；接口契约检查与生成客户端一致性检查通过。
- 新协议重点数据库、内容校验与启动用例：28 通过（也包含在后端完整回归中，不能重复计数）。
- 真实模型：3 个知识点、2 次提取模型调用（含结构修复），2 轮模拟学生对话与反馈完成。
- 实际启动：Uvicorn 健康接口 200，前端页面 200。

这些结果验证本次本地改动及知识提取到提问的数据流；未进行线上部署、全课程批量提取或真实平台账号三端验收。
