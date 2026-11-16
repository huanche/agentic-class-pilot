# 学生端

本地源码说明更新于 2026-11-16；部署状态请查具体日期的发布记录。

学生从平台登录、加入课程并选择课时，观看课件播放器后进入知识点教学，结束后查看反馈、回看和继续课后学习。

- [文档总目录](docs/README.md)：按用途查找当前说明、历史方案、实施记录和验证证据。
- [学习流程](docs/guides/student-workflow.md)与[教学阶段](docs/guides/teaching-stages.md)。
- [当前架构](docs/architecture/student-architecture-current.md)与[源码目录](docs/architecture/student-directory-layout.md)。
- [本地启动与验证](docs/guides/local-development.md)。

正式课堂使用平台 Cookie，经平台 `/api/session/*` BFF 调用学生服务；退出登录不删除学习记录。恢复时以数据库状态为准。新建三类型知识点会话采用首轮 5 轮、补强 8 轮；旧会话保留原版本。不能把历史 8/4 轮或动态教学试点方案当作全部会话的现行规则。
