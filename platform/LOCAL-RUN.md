# 本机运行

首次安装依赖并生成本机密钥：

```powershell
cd E:\LLM\code_project\ai_education_platform\platform
.\scripts\bootstrap-local.ps1
```

以后启动全部服务：

```powershell
.\scripts\start-local.ps1
```

打开 `http://localhost:8080`，管理员账号和密码写在本机未提交的 `LOCAL-ACCESS.txt`。

脚本会启动同一个 PostgreSQL 实例、平台（8080）和独立教师服务（3100）。平台拥有 `public` 中的身份、课程和选课数据；教师服务只以 `teacher` 数据库角色访问 `teacher` schema。浏览器请求通过 HttpOnly 会话 Cookie 鉴权，教师服务每个请求都会回调平台验证课程归属。

教师项目必须已安装依赖，默认目录是 `..\agent\teacher_agent\SZU-AgentEduPlatform`；其他目录可传入 `-TeacherProject`。
