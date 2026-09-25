"""Generate Chinese Mermaid ER diagrams from the live education database.

The database remains the source of truth for tables, columns, primary keys and
physical foreign keys. Cross-schema and Agent-owned relations are added as
explicit logical relations because PostgreSQL does not enforce them today.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

import psycopg


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = PLATFORM_ROOT.parent
OUTPUT = SUITE_ROOT / "docs" / "database-er-diagram.md"

TABLE_NAMES = {
    "public.agentsession": "平台Agent会话",
    "public.alembic_version": "迁移版本",
    "public.asset_blobs": "资产二进制",
    "public.asset_entries": "资产条目",
    "public.browser_session": "浏览器会话",
    "public.chapter": "课程章节",
    "public.chapterprogress": "章节学习进度",
    "public.course": "平台课程",
    "public.course_identity_repair_backup": "课程身份修复备份",
    "public.emailverification": "邮箱验证码",
    "public.enrollment": "学生选课",
    "public.item": "模板遗留条目",
    "public.teacher_course_link": "教师课程映射",
    "public.user": "平台用户",
    "teacher.mentra_artifact_files": "产物文件",
    "teacher.mentra_artifact_jobs": "产物生成任务",
    "teacher.mentra_classrooms": "已生成课堂",
    "teacher.mentra_course_access_grants": "课程访问授权",
    "teacher.mentra_course_artifacts": "课程产物",
    "teacher.mentra_course_graph_edges": "知识图谱关系",
    "teacher.mentra_course_graph_evidence": "知识图谱证据",
    "teacher.mentra_course_graph_jobs": "知识图谱生成任务",
    "teacher.mentra_course_graph_nodes": "知识图谱节点",
    "teacher.mentra_course_graph_versions": "知识图谱版本",
    "teacher.mentra_course_lesson_files": "课时内容文件",
    "teacher.mentra_course_material_files": "课程材料文件",
    "teacher.mentra_courses": "教师课程",
    "teacher.mentra_knowledge_packages": "发布知识包",
    "teacher.mentra_material_extractions": "材料解析结果",
    "teacher.mentra_teacher_agent_entries": "教师Agent内容条目",
    "teacher.mentra_teacher_agent_events": "教师Agent事件",
    "teacher.mentra_teacher_agent_owner_counters": "教师Agent用户计数器",
    "teacher.mentra_teacher_agent_owner_events": "教师Agent用户事件",
    "teacher.mentra_teacher_agent_sessions": "教师Agent会话",
    "teacher.mentra_teacher_agent_urls": "教师Agent引用网址",
    "student.after_class_reports": "课后报告",
    "student.knowledge_mastery": "知识点掌握度",
    "student.learning_events": "学习事件",
    "student.playback_progress": "播放进度",
    "student.student_messages": "学生对话消息",
    "student.student_sessions": "学生学习会话",
    "student.task_submissions": "任务提交",
}

FIELD_NAMES = {
    "id": "主键ID", "user_id": "用户ID", "owner_id": "所有者ID",
    "teacher_id": "教师ID", "student_id": "学生ID", "course_id": "课程ID",
    "external_course_id": "教师端课程ID", "chapter_id": "章节ID",
    "classroom_id": "课堂ID", "artifact_id": "产物ID", "job_id": "任务ID",
    "material_id": "材料ID", "publication_id": "发布版本ID",
    "publication_version": "发布版本号", "session_id": "会话ID",
    "session_key": "学习会话键", "thread_id": "对话线程ID",
    "entry_id": "条目ID", "parent_id": "父条目ID", "event_id": "事件ID",
    "knowledge_point_id": "知识点ID", "task_id": "教学任务ID",
    "scene_id": "场景ID", "segment_id": "片段ID", "module_id": "模块ID",
    "lesson_id": "课时ID", "storage_key": "对象存储键",
    "content_hash": "内容哈希", "source_sha256": "来源SHA256",
    "principal": "资产主体", "token_hash": "会话令牌哈希",
    "chunk_id": "材料分块ID", "node_id": "节点ID",
    "source_node_id": "起点节点ID", "target_node_id": "终点节点ID",
    "sha256": "文件SHA256", "email": "邮箱", "code_hash": "验证码哈希",
    "hashed_password": "密码哈希", "role": "角色", "full_name": "姓名",
    "student_name": "学生姓名", "is_active": "是否启用",
    "is_superuser": "是否管理员", "title": "标题", "description": "说明",
    "summary": "摘要", "status": "状态", "type": "类型",
    "artifact_type": "产物类型", "file_type": "文件类型",
    "node_type": "节点类型", "relation_type": "关系类型",
    "subject_type": "授权主体类型", "subject_id": "授权主体ID",
    "tenant_id": "租户ID", "mime": "媒体类型", "mime_type": "媒体类型",
    "file_name": "文件名", "byte_size": "字节数", "size_bytes": "文件大小",
    "bytes": "二进制内容", "content": "正文", "excerpt": "证据摘录",
    "payload": "业务数据", "properties": "扩展属性", "meta": "元数据",
    "stage": "课堂舞台", "scenes": "课堂场景", "data": "事件数据",
    "source_material_hashes": "来源材料哈希", "source": "来源",
    "event_type": "事件类型", "phase": "教学阶段", "prompt": "用户请求",
    "scope_type": "业务范围类型", "scope_id": "业务范围ID",
    "agent_key": "Agent标识", "idempotency_key": "幂等键",
    "run_token": "运行租约令牌", "state_version": "状态版本",
    "version": "版本号", "version_num": "迁移版本号", "graph_version": "图谱版本",
    "revision": "修订版本", "seq": "顺序号", "order_index": "排序号",
    "order": "顺序", "attempt": "尝试次数", "attempts": "尝试次数",
    "progress": "进度", "stars": "掌握星级", "n": "计数值",
    "page": "页码", "slide": "幻灯片号", "existing_course": "是否已有课程",
    "title_state": "标题状态", "stage_id": "阶段ID",
    "active_stage_id": "活动阶段ID", "skill_id": "技能ID", "origin": "来源入口",
    "delivered_user_message_seq": "已投递消息序号", "lease_worker_id": "租约工作进程ID",
    "lease_worker_pid": "租约进程号", "error": "错误信息",
    "created_by": "创建者", "enroll_code": "选课码", "evidence": "掌握证据",
    "url": "网址", "run_expires_at": "运行租约到期时间",
    "expires_at": "到期时间", "created_at": "创建时间", "updated_at": "更新时间",
    "published_at": "发布时间", "started_at": "开始时间",
    "last_active_at": "最后活跃时间", "ended_at": "结束时间",
    "completed_at": "完成时间", "submitted_at": "提交时间",
    "deleted_at": "删除时间", "cancel_requested_at": "取消请求时间",
    "lease_heartbeat_at": "租约心跳时间", "unreferenced_at": "取消引用时间",
    "ts": "事件时间",
}

TYPE_NAMES = {
    "uuid": "uuid", "text": "文本", "character varying": "文本",
    "integer": "整数", "bigint": "长整数", "double precision": "小数",
    "boolean": "布尔", "jsonb": "JSON", "bytea": "二进制",
    "timestamp with time zone": "时间",
}

# These are application-level joins. They are intentionally not represented as
# PostgreSQL foreign keys because the Agent schemas use text IDs and independent
# migration ownership.
LOGICAL_RELATIONS = [
    ("public.course", "teacher.mentra_courses", "一一", "课程映射"),
    ("public.user", "teacher.mentra_courses", "一多", "教师拥有"),
    ("public.user", "student.student_sessions", "一多", "学生发起"),
    ("public.course", "student.student_sessions", "一多", "课程学习"),
    ("teacher.mentra_courses", "teacher.mentra_material_extractions", "一多", "包含解析"),
    ("teacher.mentra_courses", "teacher.mentra_course_material_files", "一多", "包含材料"),
    ("teacher.mentra_courses", "teacher.mentra_artifact_jobs", "一多", "发起生成"),
    ("teacher.mentra_courses", "teacher.mentra_course_artifacts", "一多", "生成产物"),
    ("teacher.mentra_artifact_jobs", "teacher.mentra_course_artifacts", "一多", "产生"),
    ("teacher.mentra_course_artifacts", "teacher.mentra_artifact_files", "一多", "包含文件"),
    ("teacher.mentra_course_artifacts", "teacher.mentra_classrooms", "一一", "生成课堂"),
    ("teacher.mentra_courses", "teacher.mentra_course_lesson_files", "一多", "包含课时文件"),
    ("teacher.mentra_courses", "teacher.mentra_knowledge_packages", "一多", "发布知识包"),
    ("teacher.mentra_courses", "teacher.mentra_course_graph_versions", "一多", "拥有图谱版本"),
    ("teacher.mentra_course_graph_versions", "teacher.mentra_course_graph_nodes", "一多", "包含节点"),
    ("teacher.mentra_course_graph_versions", "teacher.mentra_course_graph_edges", "一多", "包含关系"),
    ("teacher.mentra_course_graph_versions", "teacher.mentra_course_graph_evidence", "一多", "包含证据"),
    ("teacher.mentra_course_graph_versions", "teacher.mentra_course_graph_jobs", "一多", "生成任务"),
    ("teacher.mentra_courses", "teacher.mentra_course_access_grants", "一多", "访问授权"),
    ("teacher.mentra_teacher_agent_sessions", "teacher.mentra_teacher_agent_entries", "一多", "产生条目"),
    ("teacher.mentra_teacher_agent_sessions", "teacher.mentra_teacher_agent_events", "一多", "产生事件"),
    ("teacher.mentra_teacher_agent_sessions", "teacher.mentra_teacher_agent_urls", "一多", "引用网址"),
    ("teacher.mentra_teacher_agent_sessions", "teacher.mentra_teacher_agent_owner_events", "一多", "归属事件"),
    ("student.student_sessions", "student.student_messages", "一多", "产生消息"),
    ("student.student_sessions", "student.learning_events", "一多", "产生事件"),
    ("student.student_sessions", "student.playback_progress", "一多", "记录播放"),
    ("student.student_sessions", "student.knowledge_mastery", "一多", "形成掌握度"),
    ("student.student_sessions", "student.task_submissions", "一多", "提交任务"),
    ("student.student_sessions", "student.after_class_reports", "一一", "生成报告"),
]


def load_env() -> None:
    for raw in (PLATFORM_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def entity_id(schema: str, table: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", f"{schema}_{table}").upper()


def field_comment(name: str) -> str:
    return FIELD_NAMES.get(name, name.replace("_", " "))


def cardinality(kind: str) -> str:
    return {"一一": "||--o|", "一多": "||--o{"}[kind]


def diagram(schema: str, tables: dict, primary_keys: set, foreign_keys: list) -> str:
    lines = ["```mermaid", "erDiagram"]
    selected = {key for key in tables if key.startswith(f"{schema}.")}
    for key in sorted(selected):
        table_schema, table_name = key.split(".", 1)
        alias = TABLE_NAMES.get(key, table_name)
        lines.append(f'    {entity_id(table_schema, table_name)}["{alias}<br/>{key}"] {{')
        for column_name, data_type, nullable in tables[key]:
            markers = []
            if (key, column_name) in primary_keys:
                markers.append("PK")
            if any(fk[0] == key and fk[1] == column_name for fk in foreign_keys):
                markers.append("FK")
            marker = f" {','.join(markers)}" if markers else ""
            required = "必填" if nullable == "NO" else "可空"
            safe_comment = field_comment(column_name).replace('"', "'")
            lines.append(
                f'        {TYPE_NAMES.get(data_type, "文本")} {column_name}{marker} "{safe_comment}；{required}"'
            )
        lines.append("    }")

    for source, source_col, target, target_col in foreign_keys:
        if source in selected and target in selected:
            s_schema, s_table = source.split(".", 1)
            t_schema, t_table = target.split(".", 1)
            lines.append(
                f'    {entity_id(t_schema, t_table)} ||--o{{ {entity_id(s_schema, s_table)} : "{field_comment(source_col)}"'
            )
    for source, target, kind, label in LOGICAL_RELATIONS:
        if source in selected and target in selected:
            ss, st = source.split(".", 1)
            ts, tt = target.split(".", 1)
            lines.append(
                f'    {entity_id(ss, st)} {cardinality(kind)} {entity_id(ts, tt)} : "{label}（逻辑）"'
            )
    lines.append("```")
    return "\n".join(lines)


def overview() -> str:
    return """```mermaid
erDiagram
    平台用户 ||--o{ 平台课程 : "教师拥有"
    平台用户 ||--o{ 学生选课 : "学生参加"
    平台课程 ||--o{ 学生选课 : "包含学生"
    平台课程 ||--|| 教师课程映射 : "映射"
    教师课程映射 ||--|| 教师课程 : "连接两个schema"
    教师课程 ||--o{ 课程材料 : "包含"
    教师课程 ||--o{ 课程产物 : "生成"
    教师课程 ||--o{ 发布知识包 : "发布"
    课程产物 ||--o| 已生成课堂 : "形成"
    平台用户 ||--o{ 学生学习会话 : "学生发起"
    平台课程 ||--o{ 学生学习会话 : "学习"
    发布知识包 ||--o{ 学生学习会话 : "锁定版本"
    已生成课堂 ||--o{ 学生学习会话 : "播放"
    学生学习会话 ||--o{ 学生对话消息 : "产生"
    学生学习会话 ||--o{ 学习事件 : "产生"
    学生学习会话 ||--o{ 播放进度 : "记录"
    学生学习会话 ||--o{ 知识点掌握度 : "形成"
    学生学习会话 ||--o{ 任务提交 : "提交"
    学生学习会话 ||--o| 课后报告 : "生成"
```"""


def main() -> None:
    load_env()
    dsn = os.environ["DATABASE_URL"].replace("+psycopg", "")
    tables: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    primary_keys: set[tuple[str, str]] = set()
    foreign_keys: list[tuple[str, str, str, str]] = []

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT table_schema, table_name, column_name, data_type, is_nullable
                   FROM information_schema.columns
                   WHERE table_schema IN ('public','teacher','student')
                   ORDER BY table_schema, table_name, ordinal_position"""
            )
            for schema, table, column, data_type, nullable in cursor.fetchall():
                tables[f"{schema}.{table}"].append((column, data_type, nullable))

            cursor.execute(
                """SELECT ns.nspname, cls.relname, att.attname
                   FROM pg_constraint con
                   JOIN pg_class cls ON cls.oid=con.conrelid
                   JOIN pg_namespace ns ON ns.oid=cls.relnamespace
                   JOIN unnest(con.conkey) WITH ORDINALITY key(attnum, ord) ON true
                   JOIN pg_attribute att ON att.attrelid=con.conrelid AND att.attnum=key.attnum
                   WHERE con.contype='p' AND ns.nspname IN ('public','teacher','student')"""
            )
            primary_keys.update((f"{s}.{t}", c) for s, t, c in cursor.fetchall())

            cursor.execute(
                """SELECT src_ns.nspname, src.relname, src_att.attname,
                          dst_ns.nspname, dst.relname, dst_att.attname
                   FROM pg_constraint con
                   JOIN pg_class src ON src.oid=con.conrelid
                   JOIN pg_namespace src_ns ON src_ns.oid=src.relnamespace
                   JOIN pg_class dst ON dst.oid=con.confrelid
                   JOIN pg_namespace dst_ns ON dst_ns.oid=dst.relnamespace
                   JOIN unnest(con.conkey) WITH ORDINALITY sk(attnum, ord) ON true
                   JOIN unnest(con.confkey) WITH ORDINALITY dk(attnum, ord) ON dk.ord=sk.ord
                   JOIN pg_attribute src_att ON src_att.attrelid=src.oid AND src_att.attnum=sk.attnum
                   JOIN pg_attribute dst_att ON dst_att.attrelid=dst.oid AND dst_att.attnum=dk.attnum
                   WHERE con.contype='f' AND src_ns.nspname IN ('public','teacher','student')"""
            )
            foreign_keys.extend(
                (f"{ss}.{st}", sc, f"{ds}.{dt}", dc)
                for ss, st, sc, ds, dt, dc in cursor.fetchall()
            )

    missing_names = sorted(set(tables) - set(TABLE_NAMES))
    if missing_names:
        raise RuntimeError(f"缺少中文表名映射: {missing_names}")

    content = f"""# 完整中文 ER 图

> 生成时间：2026-09-25。来源为当前 `education` 数据库。图中 `PK`、`FK` 表示数据库真实约束；标有“逻辑”的连线由服务代码维护，数据库暂未建立物理外键。

由于数据库共有 {len(tables)} 张表，一张图同时显示所有字段会难以阅读，因此拆成总览和三个 schema 详细图。三张详细图合计覆盖当前数据库的全部表和全部字段。

## 一、跨服务核心关系总览

{overview()}

## 二、平台 public schema（全部表与字段）

{diagram('public', tables, primary_keys, foreign_keys)}

## 三、教师 teacher schema（全部表与字段）

教师 schema 当前主要依靠 ID 和服务层维护关系，绝大多数关联是逻辑关联。

{diagram('teacher', tables, primary_keys, foreign_keys)}

## 四、学生 student schema（全部表与字段）

学生数据中的 `user_id`、`course_id`、`publication_id` 和 `classroom_id` 使用文本形式保存，通过平台服务校验，当前不是物理外键。

{diagram('student', tables, primary_keys, foreign_keys)}

## 五、跨 schema 连接键

| 来源 | 目标 | 连接方式 |
| --- | --- | --- |
| `public.teacher_course_link.course_id` | `public.course.id` | 物理外键 |
| `public.teacher_course_link.external_course_id` | `teacher.mentra_courses.id` | 逻辑一对一 |
| `teacher.mentra_courses.teacher_id` | `public.user.id` | 可信身份字符串，逻辑关联 |
| `student.*.user_id` | `public.user.id` | 逻辑关联 |
| `student.*.course_id` | `public.course.id` | 逻辑关联 |
| `student.*.publication_id` | `teacher.mentra_knowledge_packages.id` | 逻辑关联 |
| `student.*.classroom_id` | `teacher.mentra_classrooms.id` | 逻辑关联 |

## 六、阅读说明

- `JSON` 字段内部仍包含更细的嵌套业务对象，ER 图只表示关系表结构，不展开 JSON 内部结构。
- `teacher_course_link` 是平台课程与教师 Agent 课程之间最关键的桥梁。
- teacher/student schema 缺少物理外键是当前设计事实；删除或迁移数据必须经过服务层。
- `alembic_version`、`course_identity_repair_backup` 和 `item` 属于迁移、修复或模板兼容表，也保留在完整图中。
"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Generated {OUTPUT} ({len(tables)} tables)")


if __name__ == "__main__":
    main()
