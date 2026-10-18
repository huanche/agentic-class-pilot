# 教师端本地修改与测试

在项目根目录打开 PowerShell，运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-teacher-local.ps1
```

访问 <http://127.0.0.1:3200>。这是实际教师端的 Next.js 开发模式，修改源文件后会自动重新编译；修改环境配置后需要重启服务。关闭启动终端或按 Ctrl+C 停止前台服务。不要同时启动两份使用同一 `.next` 编译目录的教师端开发服务。

- 启动脚本根据自身位置定位项目，不依赖其他工程目录。
- 私有模型配置位于 `teacher_agent/.env.local`，已被 Git 忽略。Key 由服务端使用，不应写入 `NEXT_PUBLIC_*` 配置。
- 本地服务使用 JSON 文件保存课程，路径为 `teacher_agent/.runtime/data-3200/`。浏览器也保存本机编辑缓存；完整测试请使用同一个本地地址。
- 应用运行日志、临时验证文件放在 `teacher_agent/.runtime/`；课程音频等资源也保存在本项目内。
- 普通课件生成、编辑、配音、聚焦和播放可在此测试。模型与 TTS 调用仍需要联网，并使用配置账户的额度。
- 这是独立教师端开发环境。统一登录、班级发布和学生端联动需要另行启动平台、学生服务和数据库，不属于该入口。

常见修改位置：

| 内容 | 文件 |
| --- | --- |
| 教学片段生成规范、动作编译 | `teacher_agent/lib/generation/teaching-plan.ts` |
| 聚焦与讲稿检查 | `teacher_agent/lib/server/aligned-scene-actions.ts` |
| 时长预算与实测 | `teacher_agent/lib/generation/course-duration.ts` |
| 生成流程、配音与重试 | `teacher_agent/lib/hooks/use-scene-generator.ts` |
| 课程恢复与缓存加载 | `teacher_agent/lib/classroom/load-classroom.ts` |
