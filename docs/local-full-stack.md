# Windows 完整平台本地运行

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -CheckOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

访问 `http://localhost:8088`。不要在 8080、3200、8001 上登录后再跳转，这些是内部地址。启动器只在子进程中统一公共 URL，不改写配置文件。

首次安装依赖、生成配置仍按根 README 执行。此入口用于已初始化的本地数据库；若迁移版本落后，会明确失败，请先审查并在 `platform/backend` 执行本地 `alembic upgrade head`。不会自动执行迁移、重置数据库卷、轮换密码或创建用户。

## 检查与停止

`-CheckOnly` 检查配置、依赖、三角色数据库连接、迁移版本、本地 MinIO HTTP 健康和 Mailpit SMTP 欢迎消息，不启动服务、发送邮件或构建前端。TCP 端口已打开但转发异常时也会明确失败。

`-SkipInfrastructure` 用于 Docker 基础设施已经启动的情况；`-SkipBuild` 只有构建指纹与源码匹配时才允许跳过构建。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -Stop
```

停止命令核对进程命令行，只终止本次检出启动器记录的进程及其子进程，保留 Docker、数据库与所有业务数据。改动本地配置后，先停止再启动。未受管理的端口占用会明确报错，不会强行终止或复用其他项目。

## 配置原则

- 共享身份、签名和数据库配置来自被 Git 忽略的 `platform/.env`。
- 学生 `.env.local` 可以提供个人模型配置，但不能覆盖共享集成配置。
- 仅接受 `ENVIRONMENT=development`，数据库地址限定为本机 `55432/education`，拒绝 CI 和 Linux 环境运行。
- 公共地址统一为 `http://localhost:8088`，包括登录跳转、课件链接、学生入口和 iframe origin。
- `.runtime/local-dev/` 保存各服务独立日志和启动进程记录。前端更新前的学生静态产物保存在其中，方便恢复。

数据库连接失败时，先核对 `DATABASE_URL` 内密码、`POSTGRES_PASSWORD`、教师角色密码及 `STUDENT_DATABASE_URL`。已有 PostgreSQL 卷不会因为修改 `.env` 自动修改角色密码，禁止为了修复认证而删除卷。应验证已有本机凭据后修复本机配置，不把密码发到聊天或提交到 Git。

## 对线上系统的影响

本入口只由根目录 `start-local.ps1` 显式调用。应用运行代码、生产配置、数据库迁移、Dockerfile、服务器部署脚本和 GitHub Actions 均未改动。

根目录启动入口、`scripts/local_dev.py`、`scripts/local-gateway.mjs`、相关根级测试和说明文件不匹配当前三个服务的自动部署路径过滤规则。因此仅提交这批文件不会触发这些自动部署。

这个结论不适用于整个 `decouple` 分支：分支中既有的 `platform/**`、`teacher_agent/**`、`student_agent/**` 改动仍可能在合并 main 后触发自动部署。请分开审查本地启动修复与此前解耦提交。没有执行 push、合并或部署。
