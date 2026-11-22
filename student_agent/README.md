# 学生端

现行说明按 2026-11-22 工作区源码（`e9929e5`）核对。部署状态请查对应的发布记录。

学生从平台登录、加入课程并选择课时，观看课件播放器后进入知识点教学，结束后查看反馈、回看和继续课后学习。

- [文档总目录](docs/README.md)：按用途查找当前说明、历史方案、实施记录和验证证据。
- [学习流程](docs/guides/student-workflow.md)与[教学阶段](docs/guides/teaching-stages.md)。
- [当前架构](docs/architecture/student-architecture-current.md)与[源码目录](docs/architecture/student-directory-layout.md)。
- [知识点提取](docs/knowledge-extraction/README.md)与[教学实现索引](docs/knowledge-teaching/README.md)。
- [本地启动与验证](docs/guides/local-development.md)。

正式课堂使用平台 Cookie，经平台 `/api/session/*` BFF 调用学生服务。退出登录后可从课时目录恢复数据库中的学习记录。新提取的课时内容包含 3–8 个去重后的知识点。新建三类型会话的课堂首轮、补强分别最多 5、8 轮，记忆类使用题组卡，概念类和设计类使用对话。已有会话按保存的教学版本恢复。
