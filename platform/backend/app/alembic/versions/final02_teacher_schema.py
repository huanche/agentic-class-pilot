"""teacher schema core tables for the teacher agent service

Phase 3 (unified database): the platform migration owns the DDL of the
teacher agent's core course-data tables in the ``teacher`` schema. The
teacher service connects as the limited ``teacher`` role and only performs
DML. The agent-session tables (mentra_teacher_agent_*) are provisioned by
the teacher service itself via the upstream storage package's idempotent
ensureAgentSessionSchema — same split as the verified legacy topology.

Revision ID: final02
Revises: final01
"""

from alembic import op

revision = "final02"
down_revision = "final01"
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS teacher.mentra_courses (
    id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, status TEXT NOT NULL,
    title TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_courses_teacher_updated_idx
    ON teacher.mentra_courses (teacher_id, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_material_extractions (
    material_id TEXT PRIMARY KEY, course_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_material_extractions_course_idx
    ON teacher.mentra_material_extractions (course_id)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_artifact_jobs (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL, status TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_artifact_jobs_course_created_idx
    ON teacher.mentra_artifact_jobs (course_id, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_artifacts (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, course_id TEXT NOT NULL,
    teacher_id TEXT NOT NULL, artifact_type TEXT NOT NULL, status TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_artifacts_course_status_idx
    ON teacher.mentra_course_artifacts (course_id, status, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_lesson_files (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, module_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
    file_type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_lesson_files_lesson_idx
    ON teacher.mentra_course_lesson_files (course_id, module_id, lesson_id, file_type)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_classrooms (
    id TEXT PRIMARY KEY, course_id TEXT, artifact_id TEXT,
    stage JSONB NOT NULL, scenes JSONB NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_classrooms_course_idx
    ON teacher.mentra_classrooms (course_id, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_artifact_files (
    storage_key TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, sha256 TEXT NOT NULL,
    bytes BYTEA NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_artifact_files_artifact_idx
    ON teacher.mentra_artifact_files (artifact_id, updated_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_material_files (
    storage_key TEXT PRIMARY KEY, material_id TEXT NOT NULL, course_id TEXT NOT NULL,
    file_name TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL, bytes BYTEA NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_material_files_course_idx
    ON teacher.mentra_course_material_files (course_id, material_id)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_knowledge_packages (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    version INTEGER NOT NULL, status TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, published_at BIGINT,
    UNIQUE (course_id, version)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_knowledge_packages_course_status_idx
    ON teacher.mentra_knowledge_packages (course_id, status, version DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_graph_versions (
    course_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
    title TEXT NOT NULL, summary TEXT, source_material_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by TEXT NOT NULL, created_at BIGINT NOT NULL, published_at BIGINT,
    PRIMARY KEY (course_id, version)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_versions_status_idx
    ON teacher.mentra_course_graph_versions (course_id, status, version DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_graph_jobs (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    graph_version INTEGER NOT NULL, session_id TEXT NOT NULL, status TEXT NOT NULL,
    phase TEXT NOT NULL, progress INTEGER NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_jobs_course_created_idx
    ON teacher.mentra_course_graph_jobs (course_id, created_at DESC)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_graph_nodes (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    node_type TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
    module_id TEXT, lesson_id TEXT, status TEXT NOT NULL, properties JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL,
    PRIMARY KEY (course_id, graph_version, id)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_nodes_lookup_idx
    ON teacher.mentra_course_graph_nodes (course_id, graph_version, node_type, lesson_id)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_graph_edges (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, relation_type TEXT NOT NULL,
    properties JSONB NOT NULL, created_at BIGINT NOT NULL,
    PRIMARY KEY (course_id, graph_version, id)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_edges_source_idx
    ON teacher.mentra_course_graph_edges (course_id, graph_version, source_node_id)""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_edges_target_idx
    ON teacher.mentra_course_graph_edges (course_id, graph_version, target_node_id)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_graph_evidence (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    node_id TEXT NOT NULL, material_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
    page INTEGER, slide INTEGER, source_sha256 TEXT NOT NULL, excerpt TEXT,
    PRIMARY KEY (course_id, graph_version, id)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_graph_evidence_node_idx
    ON teacher.mentra_course_graph_evidence (course_id, graph_version, node_id)""",
    """CREATE TABLE IF NOT EXISTS teacher.mentra_course_access_grants (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, course_id TEXT NOT NULL,
    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, role TEXT NOT NULL,
    created_at BIGINT NOT NULL, expires_at BIGINT,
    UNIQUE (tenant_id, course_id, subject_type, subject_id)
    )""",
    """CREATE INDEX IF NOT EXISTS mentra_course_access_subject_idx
    ON teacher.mentra_course_access_grants (tenant_id, subject_type, subject_id, course_id)""",
]

TEACHER_TABLES = [
    "mentra_course_access_grants",
    "mentra_course_graph_evidence",
    "mentra_course_graph_edges",
    "mentra_course_graph_nodes",
    "mentra_course_graph_jobs",
    "mentra_course_graph_versions",
    "mentra_knowledge_packages",
    "mentra_course_material_files",
    "mentra_artifact_files",
    "mentra_classrooms",
    "mentra_course_lesson_files",
    "mentra_course_artifacts",
    "mentra_artifact_jobs",
    "mentra_material_extractions",
    "mentra_courses",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS teacher")
    for statement in STATEMENTS:
        op.execute(statement)
    # The limited teacher role gets DML only. Environments without the role
    # (plain test databases) skip the grants; the local 01-roles.sql creates it.
    op.execute(
        """
        DO $grant_teacher$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teacher') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA teacher TO teacher';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA teacher TO teacher';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA teacher GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO teacher';
          END IF;
        END
        $grant_teacher$
        """
    )


def downgrade() -> None:
    for table in TEACHER_TABLES:
        op.execute(f"DROP TABLE IF EXISTS teacher.{table}")
