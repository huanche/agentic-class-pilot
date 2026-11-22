# 学生端本地启动与验证

从仓库根目录运行。完整平台、教师播放器和学生服务的启动与代理配置见[本地全栈指南](../../../docs/local-full-stack.md)。

```powershell
cd student_agent/frontend
npm install
npm run build
cd ../..
$studentPython = if (Test-Path .\platform\.venv\Scripts\python.exe) {
    '.\platform\.venv\Scripts\python.exe'
} else {
    'python'
}
& $studentPython -m pip install -r student_agent/backend/requirements.txt
.\student_agent\start-platform.ps1
```

脚本读取 `platform/.env`，并可读取 `student_agent/.env.local` 的模型和平台客户端配置。本地学生服务监听 `127.0.0.1:8001`，公共入口从 `http://localhost:8088/login` 登录后打开。平台转发正式学习会话使用 `PLATFORM_TO_STUDENT_KEY`，内部平台接口与共享准备入队使用约定的 `STUDENT_SERVICE_KEY`。 [启动脚本](../../start-platform.ps1) · [学生内部接口](../../backend/internal_platform.py)

前端导出到 `frontend/out`，由 FastAPI 提供 `/app`。`apps/server.py`、`apps/start.py` 是兼容启动入口。

验证入口：

```powershell
python -m pytest -q student_agent/backend/tests
cd student_agent/frontend
npm run test:unit
npm run test:e2e
npm run build
```

后端测试从含学生端依赖和 pytest 的 Python 环境运行。数据库用例通过 `STUDENT_TEST_DATABASE_URL` 启用，要求专用回环 PostgreSQL 和 `student_p2_test` 用户。真实模型用例逐组显式启用。 [测试配置](../../backend/tests/conftest.py) · [发布说明中的验证入口](../releases/2026-11-13-typed-teaching.md)
