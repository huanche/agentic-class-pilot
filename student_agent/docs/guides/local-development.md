# 学生端本地启动与验证

从仓库根目录运行（本地平台已配置）：

```powershell
cd student_agent/frontend
npm install
npm run build
cd ../..
python -m pip install -r student_agent/backend/requirements.txt
.\student_agent\start-platform.ps1
```

脚本读取本机平台配置，本地学生服务使用 `127.0.0.1:8001`。从平台 `http://localhost:8088/login` 登录后进入学习。平台与学生服务须使用一致的 `PLATFORM_TO_STUDENT_KEY`；学生访问平台仍使用 `STUDENT_SERVICE_KEY`。不要将本机凭据写入文档。

前端导出到 `frontend/out`，由 FastAPI 提供 `/app`。`apps/server.py`、`apps/start.py` 是兼容启动入口。

验证入口：

```powershell
python -m pytest -q student_agent/backend/tests
cd student_agent/frontend
npm run test:unit
npm run test:e2e
npm run build
```

真实数据库与模型用例具有额外配置和隔离要求，见[发布说明中的验证入口](../releases/2026-11-13-typed-teaching.md)。文档整理本身只检查路径、内容与变更范围，不把历史测试通过数作为本次运行结果。
