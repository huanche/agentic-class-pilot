# 学生端

该目录是统一课堂项目的 Next.js 前端源码。生产构建输出到 `frontend/out/`，由根目录的
FastAPI 服务同源托管；所有教学阶段共用一个 AI 消息接口：

```http
POST /api/session/{sessionId}/message
{ "text": "学生输入" }
```

前端不提交阶段类型。后端根据会话中的 `host_phase` 决定当前执行复述评价、深入探究、
课堂讨论或普通问答。

## 开发

```powershell
npm ci
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

后端在项目根目录启动：

```powershell
python apps/start.py --no-browser
```

## 生产构建

```powershell
npm run lint
npm run build
```

之后从根目录执行 `python apps/start.py`，访问 `http://127.0.0.1:8000/`。Windows 用户
可以直接双击根目录的 `启动课堂.bat`，脚本会自动安装缺失依赖、构建前端并启动后端。

课程资源接口、会话时序和字段说明见 `docs/api/后端接口说明.md`。
