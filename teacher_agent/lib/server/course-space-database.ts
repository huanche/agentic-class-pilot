import { Pool, type PoolClient, type QueryResultRow } from 'pg';
import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseAccessGrant,
  CourseKnowledgeGraph,
  CourseKnowledgeExtractionJob,
  CourseMaterialExtraction,
  CourseSpace,
  PublishedKnowledgePackage,
} from '@/lib/course-space/types';
import type { PersistedClassroomData } from '@/lib/server/classroom-storage';

type CourseDatabaseEntity =
  | CourseSpace
  | CourseMaterialExtraction
  | CourseArtifactJob
  | CourseArtifactRecord
  | PublishedKnowledgePackage;

interface DatabaseState {
  connectionString?: string;
  pool?: Pool;
  schemaPromise?: Promise<void>;
}

const STATE_KEY = Symbol.for('mentra.course-space.database');
const globalState = globalThis as typeof globalThis & { [STATE_KEY]?: DatabaseState };
const state = (globalState[STATE_KEY] ??= {});

export function getCourseDatabaseUrl() {
  return process.env.COURSE_DATABASE_URL?.trim() || process.env.DATABASE_URL?.trim();
}

export type CourseStorageMode = 'json' | 'postgres';

export function getCourseStorageMode(): CourseStorageMode {
  const raw = (process.env.COURSE_STORAGE_MODE || 'json').trim().toLowerCase();
  if (raw !== 'json' && raw !== 'postgres') {
    throw new Error(`COURSE_STORAGE_MODE must be 'json' or 'postgres', got '${raw}'`);
  }
  return raw;
}

/** True only in the explicit postgres mode with a configured URL. */
export function isCourseDatabaseConfigured() {
  return getCourseStorageMode() === 'postgres' && Boolean(getCourseDatabaseUrl());
}

/** Fail closed: postgres mode without a URL is a misconfiguration, never a JSON fallback. */
export function assertCourseDatabaseReady() {
  if (getCourseStorageMode() !== 'postgres') return;
  if (!getCourseDatabaseUrl()) {
    throw new Error('COURSE_STORAGE_MODE=postgres requires COURSE_DATABASE_URL to be configured');
  }
}

export function getCourseDatabasePool() {
  const connectionString = getCourseDatabaseUrl();
  if (!connectionString) return undefined;
  // Shared-instance isolation: a dedicated schema keeps platform and teacher
  // data apart on one PostgreSQL instance. Validated to stay a safe SQL token.
  const schema = process.env.COURSE_DATABASE_SCHEMA?.trim();
  if (schema && !/^[a-z_][a-z0-9_]*$/.test(schema)) {
    throw new Error(`COURSE_DATABASE_SCHEMA must match ^[a-z_][a-z0-9_]*$, got '${schema}'`);
  }
  if (!state.pool || state.connectionString !== connectionString) {
    void state.pool?.end().catch(() => undefined);
    state.connectionString = connectionString;
    state.pool = new Pool({
      connectionString,
      max: 8,
      ...(schema ? { options: `-c search_path=${schema}` } : {}),
    });
    state.schemaPromise = undefined;
  }
  return state.pool;
}

const SCHEMA_STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS mentra_courses (
    id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, status TEXT NOT NULL,
    title TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_courses_teacher_updated_idx
    ON mentra_courses (teacher_id, updated_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_material_extractions (
    material_id TEXT PRIMARY KEY, course_id TEXT NOT NULL,
    source_sha256 TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_material_extractions_course_idx
    ON mentra_material_extractions (course_id)`,
  `CREATE TABLE IF NOT EXISTS mentra_artifact_jobs (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL, status TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_artifact_jobs_course_created_idx
    ON mentra_artifact_jobs (course_id, created_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_artifacts (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, course_id TEXT NOT NULL,
    teacher_id TEXT NOT NULL, artifact_type TEXT NOT NULL, status TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_artifacts_course_status_idx
    ON mentra_course_artifacts (course_id, status, updated_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_lesson_files (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, module_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
    file_type TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, content TEXT NOT NULL,
    payload JSONB NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_lesson_files_lesson_idx
    ON mentra_course_lesson_files (course_id, module_id, lesson_id, file_type)`,
  `CREATE TABLE IF NOT EXISTS mentra_classrooms (
    id TEXT PRIMARY KEY, course_id TEXT, artifact_id TEXT,
    stage JSONB NOT NULL, scenes JSONB NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_classrooms_course_idx
    ON mentra_classrooms (course_id, updated_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_artifact_files (
    storage_key TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, file_name TEXT NOT NULL,
    mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL, sha256 TEXT NOT NULL,
    bytes BYTEA NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_artifact_files_artifact_idx
    ON mentra_artifact_files (artifact_id, updated_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_material_files (
    storage_key TEXT PRIMARY KEY, material_id TEXT NOT NULL, course_id TEXT NOT NULL,
    file_name TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL, bytes BYTEA NOT NULL, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_material_files_course_idx
    ON mentra_course_material_files (course_id, material_id)`,
  `CREATE TABLE IF NOT EXISTS mentra_knowledge_packages (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    version INTEGER NOT NULL, status TEXT NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, published_at BIGINT,
    UNIQUE (course_id, version)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_knowledge_packages_course_status_idx
    ON mentra_knowledge_packages (course_id, status, version DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_graph_versions (
    course_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
    title TEXT NOT NULL, summary TEXT, source_material_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by TEXT NOT NULL, created_at BIGINT NOT NULL, published_at BIGINT,
    PRIMARY KEY (course_id, version)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_versions_status_idx
    ON mentra_course_graph_versions (course_id, status, version DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_graph_jobs (
    id TEXT PRIMARY KEY, course_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
    graph_version INTEGER NOT NULL, session_id TEXT NOT NULL, status TEXT NOT NULL,
    phase TEXT NOT NULL, progress INTEGER NOT NULL, payload JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_jobs_course_created_idx
    ON mentra_course_graph_jobs (course_id, created_at DESC)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_graph_nodes (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    node_type TEXT NOT NULL, title TEXT NOT NULL, description TEXT,
    module_id TEXT, lesson_id TEXT, status TEXT NOT NULL, properties JSONB NOT NULL,
    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL,
    PRIMARY KEY (course_id, graph_version, id)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_nodes_lookup_idx
    ON mentra_course_graph_nodes (course_id, graph_version, node_type, lesson_id)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_graph_edges (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, relation_type TEXT NOT NULL,
    properties JSONB NOT NULL, created_at BIGINT NOT NULL,
    PRIMARY KEY (course_id, graph_version, id)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_edges_source_idx
    ON mentra_course_graph_edges (course_id, graph_version, source_node_id)`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_edges_target_idx
    ON mentra_course_graph_edges (course_id, graph_version, target_node_id)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_graph_evidence (
    course_id TEXT NOT NULL, graph_version INTEGER NOT NULL, id TEXT NOT NULL,
    node_id TEXT NOT NULL, material_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
    page INTEGER, slide INTEGER, source_sha256 TEXT NOT NULL, excerpt TEXT,
    PRIMARY KEY (course_id, graph_version, id)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_graph_evidence_node_idx
    ON mentra_course_graph_evidence (course_id, graph_version, node_id)`,
  `CREATE TABLE IF NOT EXISTS mentra_course_access_grants (
    id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, course_id TEXT NOT NULL,
    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, role TEXT NOT NULL,
    created_at BIGINT NOT NULL, expires_at BIGINT,
    UNIQUE (tenant_id, course_id, subject_type, subject_id)
  )`,
  `CREATE INDEX IF NOT EXISTS mentra_course_access_subject_idx
    ON mentra_course_access_grants (tenant_id, subject_type, subject_id, course_id)`,
];

export async function ensureCourseDatabaseSchema() {
  const pool = getCourseDatabasePool();
  if (!pool) return false;
  // Shared-schema mode: migrations own the core DDL; the runtime gets DML grants only.
  if (process.env.COURSE_DATABASE_SCHEMA?.trim() && process.env.COURSE_DATABASE_MANAGE_SCHEMA !== 'true') {
    state.schemaPromise ??= Promise.resolve();
    return true;
  }
  if (!state.schemaPromise) {
    state.schemaPromise = (async () => {
      const client = await pool.connect();
      try {
        await client.query('BEGIN');
        for (const statement of SCHEMA_STATEMENTS) await client.query(statement);
        await client.query('COMMIT');
      } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined);
        state.schemaPromise = undefined;
        throw error;
      } finally {
        client.release();
      }
    })();
  }
  await state.schemaPromise;
  return true;
}

async function withDatabase<T>(fn: (client: PoolClient) => Promise<T>): Promise<T | undefined> {
  const pool = getCourseDatabasePool();
  if (!pool) return undefined;
  await ensureCourseDatabaseSchema();
  const client = await pool.connect();
  try { return await fn(client); } finally { client.release(); }
}

export async function upsertCourseDatabaseRecord(course: CourseSpace) {
  return withDatabase(async (client) => {
    await client.query('BEGIN');
    try {
      await client.query(
        `INSERT INTO mentra_courses (id, teacher_id, status, title, payload, created_at, updated_at)
         VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
         ON CONFLICT (id) DO UPDATE SET teacher_id=EXCLUDED.teacher_id, status=EXCLUDED.status,
           title=EXCLUDED.title, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at`,
        [course.id, course.teacherId, course.status, course.title, JSON.stringify(course), course.createdAt, course.updatedAt],
      );
      await client.query('DELETE FROM mentra_course_lesson_files WHERE course_id=$1', [course.id]);
      for (const courseModule of course.modules) {
        for (const lesson of courseModule.lessons) {
          for (const file of lesson.files ?? []) {
            await client.query(
              `INSERT INTO mentra_course_lesson_files
               (id,course_id,module_id,lesson_id,file_type,title,status,content,payload,created_at,updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)`,
              [file.id, course.id, courseModule.id, lesson.id, file.type, file.title, file.status,
                file.content, JSON.stringify(file), file.createdAt, file.updatedAt],
            );
          }
        }
      }
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    }
  });
}

export async function upsertMaterialExtractionDatabaseRecord(extraction: CourseMaterialExtraction) {
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_material_extractions (material_id, course_id, source_sha256, payload, created_at, updated_at)
     VALUES ($1,$2,$3,$4::jsonb,$5,$6)
     ON CONFLICT (material_id) DO UPDATE SET course_id=EXCLUDED.course_id,
       source_sha256=EXCLUDED.source_sha256, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at`,
    [extraction.materialId, extraction.courseId, extraction.sourceSha256, JSON.stringify(extraction), extraction.createdAt, Date.now()],
  ));
}

export async function readCourseFromDatabase(courseId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_courses WHERE id=$1 LIMIT 1', [courseId]);
    return result.rows[0]?.payload as CourseSpace | undefined;
  });
}

export async function readMaterialExtractionFromDatabase(materialId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_material_extractions WHERE material_id=$1', [materialId]);
    return (result.rows[0]?.payload as CourseMaterialExtraction | undefined) ?? null;
  });
}

export async function readCourseJobFromDatabase(jobId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_artifact_jobs WHERE id=$1', [jobId]);
    return (result.rows[0]?.payload as CourseArtifactJob | undefined) ?? null;
  });
}

export async function listCourseJobsFromDatabase(courseId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_artifact_jobs WHERE course_id=$1 ORDER BY updated_at DESC', [courseId]);
    return result.rows.map((row) => row.payload as CourseArtifactJob);
  });
}

/** Active (queued/running) jobs across all courses — used by the startup stale sweep. */
export async function listActiveCourseJobsFromDatabase() {
  return withDatabase(async (client) => {
    const result = await client.query(
      "SELECT payload FROM mentra_artifact_jobs WHERE status IN ('queued','running')",
    );
    return result.rows.map((row) => row.payload as CourseArtifactJob);
  });
}

export async function readKnowledgePackageFromDatabase(packageId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_knowledge_packages WHERE id=$1', [packageId]);
    return (result.rows[0]?.payload as PublishedKnowledgePackage | undefined) ?? null;
  });
}

export async function listKnowledgePackagesFromDatabase(courseId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_knowledge_packages WHERE course_id=$1 ORDER BY version DESC', [courseId]);
    return result.rows.map((row) => row.payload as PublishedKnowledgePackage);
  });
}

export async function listCoursesFromDatabase(teacherId: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT payload FROM mentra_courses WHERE teacher_id=$1 ORDER BY updated_at DESC',
      [teacherId],
    );
    return result.rows.map((row) => row.payload as CourseSpace);
  });
}

export async function upsertCourseJobDatabaseRecord(job: CourseArtifactJob) {
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_artifact_jobs (id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at)
     VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
     ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload,
       artifact_type=EXCLUDED.artifact_type, updated_at=EXCLUDED.updated_at`,
    [job.id, job.courseId, job.teacherId, job.artifactType, job.status, JSON.stringify(job), job.createdAt, job.updatedAt],
  ));
}

export async function upsertCourseArtifactDatabaseRecord(artifact: CourseArtifactRecord) {
  return withDatabase(async (client) => {
    await client.query('BEGIN');
    try {
      await client.query(
        `INSERT INTO mentra_course_artifacts (id, job_id, course_id, teacher_id, artifact_type, status, payload, created_at, updated_at)
         VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)
         ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload,
           artifact_type=EXCLUDED.artifact_type, updated_at=EXCLUDED.updated_at`,
        [artifact.id, artifact.jobId, artifact.courseId, artifact.teacherId, artifact.type, artifact.status,
          JSON.stringify(artifact), artifact.createdAt, artifact.updatedAt],
      );
      if (artifact.classroomId) {
        await client.query(
          'UPDATE mentra_classrooms SET course_id=$2,artifact_id=$3,updated_at=$4 WHERE id=$1',
          [artifact.classroomId, artifact.courseId, artifact.id, artifact.updatedAt],
        );
      }
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    }
  });
}

export async function upsertClassroomDatabaseRecord(
  classroom: PersistedClassroomData,
  links: { courseId?: string; artifactId?: string } = {},
) {
  const createdAt = Date.parse(classroom.createdAt) || Date.now();
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_classrooms
     (id,course_id,artifact_id,stage,scenes,payload,created_at,updated_at)
     VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7,$8)
     ON CONFLICT (id) DO UPDATE SET
       course_id=COALESCE(EXCLUDED.course_id,mentra_classrooms.course_id),
       artifact_id=COALESCE(EXCLUDED.artifact_id,mentra_classrooms.artifact_id),
       stage=EXCLUDED.stage,scenes=EXCLUDED.scenes,payload=EXCLUDED.payload,updated_at=EXCLUDED.updated_at`,
    [classroom.id, links.courseId ?? null, links.artifactId ?? null,
      JSON.stringify(classroom.stage), JSON.stringify(classroom.scenes), JSON.stringify(classroom), createdAt, Date.now()],
  ));
}

export async function readClassroomFromDatabase(id: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_classrooms WHERE id=$1 LIMIT 1', [id]);
    return result.rows[0]?.payload as PersistedClassroomData | undefined;
  });
}

export async function readClassroomBindingFromDatabase(id: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT course_id,artifact_id FROM mentra_classrooms WHERE id=$1 LIMIT 1',
      [id],
    );
    const row = result.rows[0];
    return row
      ? {
          courseId: row.course_id as string | null,
          artifactId: row.artifact_id as string | null,
        }
      : undefined;
  });
}

export async function upsertArtifactFileDatabaseRecord(input: {
  storageKey: string; artifactId: string; fileName: string; mimeType: string;
  bytes?: Buffer; sizeBytes: number; sha256: string;
}) {
  const now = Date.now();
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_artifact_files
     (storage_key,artifact_id,file_name,mime_type,size_bytes,sha256,bytes,created_at,updated_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
     ON CONFLICT (storage_key) DO UPDATE SET file_name=EXCLUDED.file_name,mime_type=EXCLUDED.mime_type,
       size_bytes=EXCLUDED.size_bytes,sha256=EXCLUDED.sha256,bytes=EXCLUDED.bytes,updated_at=EXCLUDED.updated_at`,
    [input.storageKey, input.artifactId, input.fileName, input.mimeType, input.sizeBytes,
      input.sha256, input.bytes ?? null, now],
  ));
}

export async function readArtifactFileFromDatabase(storageKey: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT file_name,mime_type,bytes FROM mentra_artifact_files WHERE storage_key=$1 LIMIT 1',
      [storageKey],
    );
    const row = result.rows[0];
    return row ? { fileName: row.file_name as string, mimeType: row.mime_type as string, bytes: row.bytes as Buffer | null } : undefined;
  });
}

export async function upsertCourseMaterialFileDatabaseRecord(input: {
  storageKey: string;
  materialId: string;
  courseId: string;
  fileName: string;
  mimeType: string;
  bytes?: Buffer;
  sizeBytes: number;
  sha256: string;
}) {
  const now = Date.now();
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_course_material_files
     (storage_key,material_id,course_id,file_name,mime_type,size_bytes,sha256,bytes,created_at,updated_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)
     ON CONFLICT (storage_key) DO UPDATE SET file_name=EXCLUDED.file_name,mime_type=EXCLUDED.mime_type,
       size_bytes=EXCLUDED.size_bytes,sha256=EXCLUDED.sha256,bytes=EXCLUDED.bytes,updated_at=EXCLUDED.updated_at`,
    [input.storageKey, input.materialId, input.courseId, input.fileName, input.mimeType,
      input.sizeBytes, input.sha256, input.bytes ?? null, now],
  ));
}

export async function readCourseMaterialFileFromDatabase(storageKey: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT bytes FROM mentra_course_material_files WHERE storage_key=$1 LIMIT 1',
      [storageKey],
    );
    return result.rows[0]?.bytes as Buffer | null | undefined;
  });
}

export async function deleteCourseArtifactDatabaseRecord(artifactId: string) {
  return withDatabase(async (client) => {
    await client.query('BEGIN');
    try {
      await client.query('DELETE FROM mentra_artifact_files WHERE artifact_id=$1', [artifactId]);
      await client.query('UPDATE mentra_classrooms SET artifact_id=NULL WHERE artifact_id=$1', [artifactId]);
      await client.query('DELETE FROM mentra_course_artifacts WHERE id=$1', [artifactId]);
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    }
  });
}

export async function upsertKnowledgePackageDatabaseRecord(pkg: PublishedKnowledgePackage) {
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_knowledge_packages (id, course_id, teacher_id, version, status, payload, created_at, published_at)
     VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
     ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status, payload=EXCLUDED.payload,
       version=EXCLUDED.version, published_at=EXCLUDED.published_at`,
    [pkg.id, pkg.courseId, pkg.teacherId, pkg.version, pkg.status, JSON.stringify(pkg), pkg.createdAt, pkg.publishedAt ?? null],
  ));
}

function payloads<T extends CourseDatabaseEntity>(rows: QueryResultRow[]): T[] {
  return rows.map((row) => row.payload as T);
}

export async function listCourseArtifactsFromDatabase(courseId: string, statuses?: CourseArtifactRecord['status'][]) {
  return withDatabase(async (client) => {
    const result = statuses?.length
      ? await client.query('SELECT payload FROM mentra_course_artifacts WHERE course_id=$1 AND status=ANY($2::text[]) ORDER BY updated_at DESC', [courseId, statuses])
      : await client.query('SELECT payload FROM mentra_course_artifacts WHERE course_id=$1 ORDER BY updated_at DESC', [courseId]);
    return payloads<CourseArtifactRecord>(result.rows);
  });
}

export async function readCourseArtifactFromDatabase(artifactId: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT payload FROM mentra_course_artifacts WHERE id=$1 LIMIT 1',
      [artifactId],
    );
    return result.rows[0]?.payload as CourseArtifactRecord | undefined;
  });
}

export async function readPublishedKnowledgePackageFromDatabase(courseId: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      `SELECT payload FROM mentra_knowledge_packages
       WHERE course_id=$1 AND status='published' ORDER BY version DESC LIMIT 1`,
      [courseId],
    );
    return result.rows[0]?.payload as PublishedKnowledgePackage | undefined;
  });
}

export async function saveCourseKnowledgeGraphToDatabase(graph: CourseKnowledgeGraph) {
  return withDatabase(async (client) => {
    await client.query('BEGIN');
    try {
      await client.query(
        `INSERT INTO mentra_course_graph_versions
         (course_id,version,status,title,summary,source_material_hashes,created_by,created_at,published_at)
         VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9)
         ON CONFLICT (course_id,version) DO UPDATE SET status=EXCLUDED.status,title=EXCLUDED.title,
         summary=EXCLUDED.summary,source_material_hashes=EXCLUDED.source_material_hashes,
         published_at=EXCLUDED.published_at`,
        [graph.courseId, graph.version, graph.status, graph.title, graph.summary ?? null,
          JSON.stringify(graph.sourceMaterialHashes), graph.createdBy, graph.createdAt, graph.publishedAt ?? null],
      );
      await client.query('DELETE FROM mentra_course_graph_evidence WHERE course_id=$1 AND graph_version=$2', [graph.courseId, graph.version]);
      await client.query('DELETE FROM mentra_course_graph_edges WHERE course_id=$1 AND graph_version=$2', [graph.courseId, graph.version]);
      await client.query('DELETE FROM mentra_course_graph_nodes WHERE course_id=$1 AND graph_version=$2', [graph.courseId, graph.version]);
      for (const node of graph.nodes) {
        await client.query(
          `INSERT INTO mentra_course_graph_nodes
           (course_id,graph_version,id,node_type,title,description,module_id,lesson_id,status,properties,created_at,updated_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12)`,
          [graph.courseId, graph.version, node.id, node.type, node.title, node.description ?? null,
            node.moduleId ?? null, node.lessonId ?? null, node.status, JSON.stringify(node.properties), node.createdAt, node.updatedAt],
        );
        for (const evidence of node.evidence) {
          await client.query(
            `INSERT INTO mentra_course_graph_evidence
             (course_id,graph_version,id,node_id,material_id,chunk_id,page,slide,source_sha256,excerpt)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
            [graph.courseId, graph.version, evidence.id, node.id, evidence.materialId, evidence.chunkId,
              evidence.page ?? null, evidence.slide ?? null, evidence.sourceSha256, evidence.excerpt ?? null],
          );
        }
      }
      for (const edge of graph.edges) {
        await client.query(
          `INSERT INTO mentra_course_graph_edges
           (course_id,graph_version,id,source_node_id,target_node_id,relation_type,properties,created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8)`,
          [graph.courseId, graph.version, edge.id, edge.sourceNodeId, edge.targetNodeId,
            edge.type, JSON.stringify(edge.properties), edge.createdAt],
        );
      }
      await client.query('COMMIT');
      return graph;
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    }
  });
}

export async function upsertCourseKnowledgeExtractionJob(job: CourseKnowledgeExtractionJob) {
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_course_graph_jobs
     (id,course_id,teacher_id,graph_version,session_id,status,phase,progress,payload,created_at,updated_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)
     ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,phase=EXCLUDED.phase,
       progress=EXCLUDED.progress,payload=EXCLUDED.payload,updated_at=EXCLUDED.updated_at`,
    [job.id, job.courseId, job.teacherId, job.graphVersion, job.sessionId, job.status,
      job.phase, job.progress, JSON.stringify(job), job.createdAt, job.updatedAt],
  ));
}

export async function readCourseKnowledgeExtractionJob(jobId: string) {
  return withDatabase(async (client) => {
    const result = await client.query('SELECT payload FROM mentra_course_graph_jobs WHERE id=$1 LIMIT 1', [jobId]);
    return result.rows[0]?.payload as CourseKnowledgeExtractionJob | undefined;
  });
}

export async function listCourseKnowledgeExtractionJobs(courseId: string) {
  return withDatabase(async (client) => {
    const result = await client.query(
      'SELECT payload FROM mentra_course_graph_jobs WHERE course_id=$1 ORDER BY created_at DESC',
      [courseId],
    );
    return result.rows.map((row) => row.payload as CourseKnowledgeExtractionJob);
  });
}

export async function readCourseKnowledgeGraphFromDatabase(
  courseId: string,
  options: { version?: number; publishedOnly?: boolean } = {},
) {
  return withDatabase(async (client) => {
    const versionResult = options.version
      ? await client.query('SELECT * FROM mentra_course_graph_versions WHERE course_id=$1 AND version=$2 LIMIT 1', [courseId, options.version])
      : await client.query(
          `SELECT * FROM mentra_course_graph_versions WHERE course_id=$1
           ${options.publishedOnly ? "AND status='published'" : ''} ORDER BY version DESC LIMIT 1`,
          [courseId],
        );
    const row = versionResult.rows[0];
    if (!row || (options.publishedOnly && row.status !== 'published')) return null;
    const [nodesResult, edgesResult, evidenceResult] = await Promise.all([
      client.query('SELECT * FROM mentra_course_graph_nodes WHERE course_id=$1 AND graph_version=$2 ORDER BY node_type,title', [courseId, row.version]),
      client.query('SELECT * FROM mentra_course_graph_edges WHERE course_id=$1 AND graph_version=$2 ORDER BY id', [courseId, row.version]),
      client.query('SELECT * FROM mentra_course_graph_evidence WHERE course_id=$1 AND graph_version=$2 ORDER BY id', [courseId, row.version]),
    ]);
    const evidenceByNode = new Map<string, CourseKnowledgeGraph['nodes'][number]['evidence']>();
    for (const item of evidenceResult.rows) {
      const evidence = { id:item.id, courseId:item.course_id, graphVersion:item.graph_version, nodeId:item.node_id,
        materialId:item.material_id, chunkId:item.chunk_id, page:item.page ?? undefined, slide:item.slide ?? undefined,
        sourceSha256:item.source_sha256, excerpt:item.excerpt ?? undefined };
      evidenceByNode.set(item.node_id, [...(evidenceByNode.get(item.node_id) ?? []), evidence]);
    }
    return {
      courseId, version: row.version, status: row.status, title: row.title, summary: row.summary ?? undefined,
      sourceMaterialHashes: row.source_material_hashes ?? [], createdBy: row.created_by,
      createdAt: Number(row.created_at), publishedAt: row.published_at ? Number(row.published_at) : undefined,
      nodes: nodesResult.rows.map((item) => ({ id:item.id, courseId:item.course_id, graphVersion:item.graph_version,
        type:item.node_type, title:item.title, description:item.description ?? undefined, moduleId:item.module_id ?? undefined,
        lessonId:item.lesson_id ?? undefined, status:item.status, properties:item.properties ?? {},
        evidence:evidenceByNode.get(item.id) ?? [], createdAt:Number(item.created_at), updatedAt:Number(item.updated_at) })),
      edges: edgesResult.rows.map((item) => ({ id:item.id, courseId:item.course_id, graphVersion:item.graph_version,
        sourceNodeId:item.source_node_id, targetNodeId:item.target_node_id, type:item.relation_type,
        properties:item.properties ?? {}, createdAt:Number(item.created_at) })),
    } as CourseKnowledgeGraph;
  });
}

export async function publishCourseKnowledgeGraphInDatabase(courseId: string, version: number) {
  return withDatabase(async (client) => {
    await client.query('BEGIN');
    try {
      await client.query("UPDATE mentra_course_graph_versions SET status='superseded' WHERE course_id=$1 AND status='published'", [courseId]);
      const result = await client.query(
        "UPDATE mentra_course_graph_versions SET status='published',published_at=$3 WHERE course_id=$1 AND version=$2 RETURNING version",
        [courseId, version, Date.now()],
      );
      await client.query('COMMIT');
      return result.rowCount === 1;
    } catch (error) { await client.query('ROLLBACK'); throw error; }
  });
}

export async function upsertCourseAccessGrant(grant: CourseAccessGrant) {
  return withDatabase(async (client) => client.query(
    `INSERT INTO mentra_course_access_grants
     (id,tenant_id,course_id,subject_type,subject_id,role,created_at,expires_at)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
     ON CONFLICT (tenant_id,course_id,subject_type,subject_id)
     DO UPDATE SET role=EXCLUDED.role,expires_at=EXCLUDED.expires_at`,
    [grant.id, grant.tenantId, grant.courseId, grant.subjectType, grant.subjectId,
      grant.role, grant.createdAt, grant.expiresAt ?? null],
  ));
}

export async function getCourseDatabaseHealth() {
  const configured = isCourseDatabaseConfigured();
  if (!configured) return { configured: false, connected: false, driver: 'postgresql' as const };
  try {
    const result = await withDatabase(async (client) => client.query('SELECT current_database() AS database, NOW() AS checked_at'));
    return { configured: true, connected: true, driver: 'postgresql' as const, database: result?.rows[0]?.database };
  } catch (error) {
    return { configured: true, connected: false, driver: 'postgresql' as const, error: error instanceof Error ? error.message : String(error) };
  }
}
