# 教师端三单元拆分与底座集成

本目录定义第一阶段的无中断拆分。现有页面、API和数据结构不迁移、不删除；新增稳定边界供SaaS底座接入。

## 三个交付单元

1. 教师工作台前端：`/teacher-workspace?workspace={courseId}`
2. 课程播放器：`/classroom-player/{classroomId}`
3. Agent与生成服务：`/api/teacher-agent/*`，并继续复用现有 `/api/course-space`、`/api/generate`、`/api/classroom`

当前三个单元仍由同一Next.js镜像提供，以保证功能不回归。物理拆成三个镜像时只需保持这些公开URL和 `@mentra/integration-contract` 不变。

## 底座嵌入

```html
<iframe
  src="https://teacher.example.com/teacher-workspace?workspace=COURSE_ID"
  title="教师工作台"
  allow="microphone; clipboard-read; clipboard-write; fullscreen"
></iframe>
```

部署教师端时设置：

```env
NEXT_PUBLIC_SAAS_HOST_ORIGIN=https://saas.example.com
ALLOWED_FRAME_ANCESTORS=https://saas.example.com
```

教师端会向该精确Origin发送版本化的 `TEACHER_WORKSPACE_READY` 和 `WORK_SCOPE_CHANGED` 消息。未配置时不发送，对当前独立运行模式没有影响。

## 验证入口

```text
GET  /api/teacher-agent/capabilities
POST /api/teacher-agent/plan
POST /api/teacher-agent/execute
GET  /teacher-workspace?workspace={courseId}
GET  /classroom-player/{classroomId}
```

## 下一阶段物理拆分

- 将教师工作台组件迁入独立前端仓库或应用，但保留入口URL。
- 将播放器及 `@openmaic/renderer`、`@openmaic/editor`、`@openmaic/dsl` 构建成独立镜像。
- 将课程、生成、图谱和课件API迁入独立服务，网关维持当前公开API路径。
- 将浏览器中的关键生成状态迁入服务端GenerationJob检查点。

这一顺序允许底座先完成集成，再逐步移动实现，不需要一次性切换全部流量。
