# 学生智能体课程数据接口

## 1. 定位与发布边界

该接口为学生智能体提供课程结构、已审核知识包、课程知识图谱、教学产物和互动课件。接口只返回已经发布的数据；教师草稿、审核中产物、教师会话和原始上传材料不会暴露。

基础路径：`/api/student-agent/v1`

所有请求必须使用服务端密钥：

```http
Authorization: Bearer <STUDENT_AGENT_API_KEY>
```

密钥只应配置在学生智能体服务端，不能写入浏览器代码或移动端安装包。

## 2. 获取课程学习上下文

```http
GET /api/student-agent/v1/courses/{courseId}
```

成功响应：

```json
{
  "success": true,
  "schemaVersion": "1.0",
  "course": {
    "id": "sx2QQqfZUm48",
    "title": "现代交换原理",
    "modules": [
      {
        "id": "module-id",
        "title": "课件生成",
        "order": 1,
        "lessons": [
          {
            "id": "lesson-id",
            "title": "第1周",
            "order": 1,
            "objectives": [],
            "files": [
              {
                "id": "file-id",
                "type": "knowledge-points",
                "title": "知识点",
                "content": "...",
                "status": "ready"
              }
            ]
          }
        ]
      }
    ]
  },
  "knowledgePackage": {},
  "knowledgeGraph": null,
  "artifacts": []
}
```

`files` 只包含 `ready` 文件。`knowledgeGraph` 在尚未发布图谱时为 `null`。

## 3. 获取单项教学产物

```http
GET /api/student-agent/v1/courses/{courseId}/artifacts/{artifactId}
```

仅当产物状态为 `published` 且课程已有发布知识包时返回。响应中的 `content` 是规范 Markdown，`htmlContent` 是经过清理的展示 HTML，`citations` 用于来源追踪。

## 4. 获取互动课件本体

```http
GET /api/student-agent/v1/courses/{courseId}/classrooms/{classroomId}
```

返回 OpenMAIC 课堂的 `stage` 与完整 `scenes`，包括页面元素、智能体配置和讲稿动作。只有与该课程已发布产物关联的课堂才能读取。

如果产物索引存在但历史课件本体已经丢失，接口返回 HTTP `410`，不会返回一个空课件冒充成功结果。

## 5. 状态码

| HTTP | 含义 |
| --- | --- |
| 200 | 成功 |
| 401 | Bearer Token 错误 |
| 404 | 课程、产物或已发布版本不存在 |
| 410 | 历史课件索引存在，但课件本体已丢失 |
| 503 | 服务端未配置 `STUDENT_AGENT_API_KEY` |

错误响应统一为：

```json
{
  "success": false,
  "errorCode": "INVALID_REQUEST",
  "error": "已发布课程不存在"
}
```

## 6. PostgreSQL 启用与迁移

配置：

```dotenv
COURSE_DATABASE_URL=postgresql://openmaic:strong-password@postgres:5432/openmaic
STUDENT_AGENT_API_KEY=<至少32字节随机密钥>
```

首次连接会自动创建课程表。把现有 JSON、课堂和附件迁入 PostgreSQL：

```bash
pnpm migrate:course-postgres
```

检查连接状态：

```http
GET /api/health
```

查看 `capabilities.courseDatabase`：`configured=true` 且 `connected=true` 才表示数据库已实际启用。

迁移是幂等的，可以重复执行。输出中的 `missingClassrooms` 是已有课件索引但缺少课堂本体的历史记录，需要重新生成课件，无法从41字的索引说明中还原原始页面。

## 7. 数据一致性

- `mentra_courses` 保存课程快照。
- `mentra_course_lesson_files` 按课程、模块、课时标准化保存课时文件。
- `mentra_course_artifacts` 保存产物正文、审核状态、引用和课堂关联。
- `mentra_classrooms` 保存完整 OpenMAIC `stage` 和 `scenes`。
- `mentra_artifact_files` 保存附件二进制、MIME、大小和 SHA-256。
- `mentra_course_material_files` 保存教师上传材料的二进制、MIME、大小和 SHA-256。
- `mentra_knowledge_packages` 与知识图谱表只向学生接口暴露已发布版本。

课程快照与全部课时文件在同一事务中更新；产物与课堂关联在同一事务中更新。文件系统继续作为开发环境回退层，配置 PostgreSQL 后读取优先使用数据库中的课堂和附件。
