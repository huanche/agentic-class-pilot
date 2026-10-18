# 教师课件后台生成任务

教师课程工作区确认大纲后，将完整大纲、画布、素材和生成设置提交给服务器。收到任务受理响应并进入任务进度页后，可以离开页面、关闭浏览器或退出教师账号。页面、讲稿、聚焦、配音、时长校正及归档均由服务器继续执行。素材准备和大纲审核仍需先完成；旧版本已经启动的浏览器任务不会自动迁移。

重新打开课程工作区，通过“最近任务”查看所有任务；生成中的任务同时显示已完成页数、当前阶段与进度。可在任务详情或列表中取消尚未完成的后台课件任务。取消状态持久化，不会被晚到的进度或完成回调覆盖。已完成页面保留，取消任务不生成正式课件产物索引。完成的课件进入待审核状态，不自动发布给学生。

## 执行与保存

- `POST /api/course-space/:courseId/courseware-jobs`：确认大纲后的幂等提交；同一会话不会重复启动任务。
- `GET /api/course-space/jobs/:jobId`：持久化状态与进度，刷新或换浏览器均可读取。
- `PATCH /api/course-space/jobs/:jobId`，请求体 `{"action":"cancel"}`：取消当前教师有权操作的任务。
- 服务端复用现有 `scene-content`、`scene-actions`、TTS 和时长校正逻辑。内容与动作请求有限重试；取消信号传递给正在执行的请求，且不会继续启动后续页面。单次页面请求最长五分钟；后台配音单片段最长两分钟，失败即结束当前任务。
- 每页完整生成后保存课堂快照；服务器任务拥有的未完成课堂禁止启动浏览器续生成，也禁止旧浏览器快照覆盖服务器进度。原有普通课堂的编辑与保存行为保留。
- 默认最多同时执行两个后台课件任务，额外任务排队。可通过 `COURSEWARE_JOB_CONCURRENCY` 配置，范围为 1–8。
- 任务状态复用课程存储，支持 JSON 或 PostgreSQL。生成输入临时保存在 `CLASSROOM_JOBS_DATA_DIR` 的任务文件中；完成、取消后清理输入，已完成课堂和任务记录保留。模型凭证只在内存中使用，不写入任务文件。图片及导入 PPT 的浏览器资源在提交前转换成独立素材，后台执行不依赖 IndexedDB。

本地启动脚本把数据保存在本项目的 `teacher_agent/.runtime/data-3200/`。当前实现面向项目现有的单实例、持续运行的 Node/Next 服务，以 `after()` 启动独立于浏览器请求的工作进程内任务，不需要新建项目外的服务目录。

关闭浏览器不影响执行；关闭本地电脑、停止 Node 服务或服务器重启会中断当前执行。心跳停止的任务会按现有超时巡检转为失败，保留已完成页面；本次未实现多实例任务租约、进程崩溃后的自动恢复，也不能部署到会在请求时限到达后终止后台回调的短时函数环境。

## 验证

针对性测试覆盖：无需浏览器轮询完成全部页面、重复提交、排队取消、执行中取消、中途快照、完成与取消竞争、晚到进度不能覆盖取消、服务器课堂不启动客户端重复生成，以及既有时长校正和配音行为。

在 `teacher_agent` 下运行：

```powershell
node node_modules/vitest/vitest.mjs run tests/server/background-courseware.test.ts tests/course-space/server-course-space.test.ts tests/course-space/stale-job-sweep.test.ts tests/classroom/classroom-server-sync.test.ts tests/classroom/load-classroom.test.ts tests/store/stage-generation-complete.test.ts tests/server/classroom-media-generation.test.ts tests/generation/course-duration-calibration.test.ts tests/audio/tts-provider-guard.test.ts --maxWorkers=1
node node_modules/typescript/bin/tsc --noEmit --incremental false
```

实际验证应在确认后台受理后关闭任务页，等待服务器继续生成，再打开课程的“最近任务”；另开一项生成任务测试取消并刷新，确认状态保持“已取消”，且后续页面不再生成。真实模型或 TTS 服务不可达时应显示失败，不能把不完整、缺配音的课程标记为完成。
