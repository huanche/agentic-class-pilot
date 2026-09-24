import { randomUUID } from 'node:crypto';
import { managesRuntimeSchema } from '@/lib/server/platform-runtime';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { PoolClient } from 'pg';
import {
  AGENT_SESSION_LIFECYCLE,
  type AgentSessionMeta,
  type PersistedAgentSessionEvent,
} from '@openmaic/storage';
import {
  ensureAgentSessionSchema,
  PgAgentSessionStore,
  type AgentSessionTableNames,
} from '@openmaic/storage/agent-session/pg';

import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseMaterialExtraction,
  CourseSpace,
  PublishedKnowledgePackage,
} from '@/lib/course-space/types';
import {
  ensureCourseDatabaseSchema,
  getCourseDatabasePool,
  isCourseDatabaseConfigured,
  listCourseArtifactsFromDatabase,
  deleteCourseArtifactDatabaseRecord,
  readPublishedKnowledgePackageFromDatabase,
  upsertCourseArtifactDatabaseRecord,
  upsertCourseDatabaseRecord,
  upsertCourseJobDatabaseRecord,
  upsertKnowledgePackageDatabaseRecord,
  upsertMaterialExtractionDatabaseRecord,
} from '@/lib/server/course-space-database';
import { writeJsonFileAtomic } from '@/lib/server/classroom-storage';

const TEACHER_SESSION_TABLES: AgentSessionTableNames = {
  sessions: 'mentra_teacher_agent_sessions',
  events: 'mentra_teacher_agent_events',
  entries: 'mentra_teacher_agent_entries',
  ownerEventCounters: 'mentra_teacher_agent_owner_counters',
  ownerEvents: 'mentra_teacher_agent_owner_events',
  urls: 'mentra_teacher_agent_urls',
};

export interface TeacherAgentTurnLease {
  sessionId: string;
  workerId: string;
  attempt: number;
  resumed: boolean;
}

export interface CourseSpaceStorageAdapter {
  readonly kind: 'postgres-openmaic' | 'file-fallback';
  saveCourse(course: CourseSpace): Promise<void>;
  saveMaterialExtraction(extraction: CourseMaterialExtraction): Promise<void>;
  saveJob(job: CourseArtifactJob): Promise<void>;
  saveArtifact(artifact: CourseArtifactRecord): Promise<void>;
  deleteArtifact(artifactId: string): Promise<void>;
  saveKnowledgePackage(pkg: PublishedKnowledgePackage): Promise<void>;
  listArtifacts(
    courseId: string,
    statuses?: CourseArtifactRecord['status'][],
  ): Promise<CourseArtifactRecord[] | undefined>;
  readPublishedKnowledgePackage(courseId: string): Promise<PublishedKnowledgePackage | undefined>;
  beginTeacherTurn(input: {
    sessionId: string;
    teacherId: string;
    courseId: string;
    message: string;
  }): Promise<TeacherAgentTurnLease | undefined>;
  completeTeacherTurn(
    lease: TeacherAgentTurnLease | undefined,
    output: { text: string; mode: string; action?: unknown; plan?: unknown },
  ): Promise<void>;
  failTeacherTurn(lease: TeacherAgentTurnLease | undefined, error: unknown): Promise<void>;
  readTeacherEvents(sessionId: string, after?: number): Promise<PersistedAgentSessionEvent[]>;
  getTeacherSession(sessionId: string): Promise<AgentSessionMeta | null>;
  listTeacherSessions(courseId: string, teacherId: string): Promise<AgentSessionMeta[]>;
}

let agentStorePromise: Promise<PgAgentSessionStore | undefined> | undefined;

type FileTeacherSession = {
  meta: AgentSessionMeta;
  events: PersistedAgentSessionEvent[];
};

const FILE_SESSION_DIR = path.join(
  process.env.COURSE_SPACES_DATA_DIR
    ? path.resolve(process.env.COURSE_SPACES_DATA_DIR)
    : path.join(process.cwd(), 'data', 'course-spaces'),
  'teacher-agent-sessions',
);
const fileSessionLocks = new Map<string, Promise<void>>();

function fileSessionPath(sessionId: string) {
  if (!/^[a-zA-Z0-9_-]+$/u.test(sessionId)) throw new Error('无效的教师会话 ID');
  return path.join(FILE_SESSION_DIR, `${sessionId}.json`);
}

async function readFileSession(sessionId: string): Promise<FileTeacherSession | null> {
  try {
    return JSON.parse(await fs.readFile(fileSessionPath(sessionId), 'utf8')) as FileTeacherSession;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

async function listFileSessions(): Promise<FileTeacherSession[]> {
  try {
    const names = (await fs.readdir(FILE_SESSION_DIR)).filter((name) => name.endsWith('.json'));
    const values = await Promise.all(
      names.map((name) => readFileSession(name.slice(0, -5))),
    );
    return values.filter((item): item is FileTeacherSession => item !== null);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

async function updateFileSession<T>(
  sessionId: string,
  update: (current: FileTeacherSession | null) => { session: FileTeacherSession; result: T },
): Promise<T> {
  const previous = fileSessionLocks.get(sessionId) ?? Promise.resolve();
  let release!: () => void;
  const currentLock = new Promise<void>((resolve) => (release = resolve));
  fileSessionLocks.set(sessionId, currentLock);
  try {
    await previous;
    const { session, result } = update(await readFileSession(sessionId));
    await writeJsonFileAtomic(fileSessionPath(sessionId), session);
    return result;
  } finally {
    release();
    if (fileSessionLocks.get(sessionId) === currentLock) fileSessionLocks.delete(sessionId);
  }
}

function appendFileEvent(
  session: FileTeacherSession,
  type: string,
  data: unknown,
  attempt = session.meta.attempt,
) {
  session.events.push({
    id: (session.events.at(-1)?.id ?? 0) + 1,
    ts: Date.now(),
    attempt,
    type,
    data,
  });
  session.meta.updatedAt = Date.now();
}

async function createAgentStore(): Promise<PgAgentSessionStore | undefined> {
  const pool = getCourseDatabasePool();
  if (!pool) return undefined;
  await ensureCourseDatabaseSchema();
  if (managesRuntimeSchema()) {
    await ensureAgentSessionSchema(pool, TEACHER_SESSION_TABLES);
  } else {
    // Platform migrations own DDL. Fail explicitly if the deployment is incomplete.
    for (const table of Object.values(TEACHER_SESSION_TABLES)) {
      await pool.query(`SELECT 1 FROM "${table}" LIMIT 0`);
    }
  }
  return new PgAgentSessionStore(pool, {
    tableNames: TEACHER_SESSION_TABLES,
    withTransaction: async <T>(operation: (transaction: PoolClient) => Promise<T>) => {
      const client = await pool.connect();
      try {
        await client.query('BEGIN');
        const result = await operation(client);
        await client.query('COMMIT');
        return result;
      } catch (error) {
        await client.query('ROLLBACK').catch(() => undefined);
        throw error;
      } finally {
        client.release();
      }
    },
  });
}

async function getAgentStore() {
  if (!isCourseDatabaseConfigured()) return undefined;
  agentStorePromise ??= createAgentStore().catch((error) => {
    agentStorePromise = undefined;
    throw error;
  });
  return agentStorePromise;
}

const adapter: CourseSpaceStorageAdapter = {
  get kind() {
    return isCourseDatabaseConfigured() ? 'postgres-openmaic' : 'file-fallback';
  },
  async saveCourse(course) { await upsertCourseDatabaseRecord(course); },
  async saveMaterialExtraction(extraction) { await upsertMaterialExtractionDatabaseRecord(extraction); },
  async saveJob(job) { await upsertCourseJobDatabaseRecord(job); },
  async saveArtifact(artifact) { await upsertCourseArtifactDatabaseRecord(artifact); },
  async deleteArtifact(artifactId) { await deleteCourseArtifactDatabaseRecord(artifactId); },
  async saveKnowledgePackage(pkg) { await upsertKnowledgePackageDatabaseRecord(pkg); },
  listArtifacts: listCourseArtifactsFromDatabase,
  readPublishedKnowledgePackage: readPublishedKnowledgePackageFromDatabase,

  async beginTeacherTurn({ sessionId, teacherId, courseId, message }) {
    const store = await getAgentStore();
    if (!store) {
      return updateFileSession(sessionId, (existing) => {
        const now = Date.now();
        const session: FileTeacherSession = existing ?? {
          meta: {
            id: sessionId,
            ownerId: teacherId,
            prompt: `教师课程工作区：${courseId}`,
            stageId: courseId,
            skillId: 'mentra-teacher-workspace',
            origin: 'course-space',
            existingCourse: true,
            status: 'succeeded',
            attempt: 0,
            deliveredUserMessageSeq: 0,
            createdAt: now,
            updatedAt: now,
          },
          events: [],
        };
        if (session.meta.ownerId !== teacherId || session.meta.stageId !== courseId)
          throw new Error('教师会话与当前课程不匹配');
        const attempt = session.meta.attempt + 1;
        const resumed = session.events.length > 0;
        session.meta.attempt = attempt;
        session.meta.status = 'running';
        session.meta.error = undefined;
        session.meta.deliveredUserMessageSeq += 1;
        appendFileEvent(session, 'user_message', { text: message }, attempt);
        appendFileEvent(
          session,
          resumed ? AGENT_SESSION_LIFECYCLE.sessionResumed : AGENT_SESSION_LIFECYCLE.sessionStart,
          { courseId },
          attempt,
        );
        return {
          session,
          result: {
            sessionId,
            workerId: `teacher-file-${process.pid}-${randomUUID()}`,
            attempt,
            resumed,
          },
        };
      });
    }
    let session = await store.getSession(sessionId);
    if (!session) {
      session = await store.createSession({
        id: sessionId,
        ownerId: teacherId,
        prompt: `教师课程工作区：${courseId}`,
        stageId: courseId,
        skillId: 'mentra-teacher-workspace',
        origin: 'course-space',
        existingCourse: true,
        status: 'succeeded',
      });
    }
    if (session.ownerId !== teacherId || session.stageId !== courseId) {
      throw new Error('教师会话与当前课程不匹配');
    }
    await store.postUserMessage(sessionId, { text: message }, { expectedOwnerId: teacherId });
    const resumed = await store.hasSessionRunHistory(sessionId);
    const workerId = `teacher-api-${process.pid}-${randomUUID()}`;
    const claimed = await store.claimNextSession(workerId, process.pid, {
      sessionId,
      leaseTtlMs: 2 * 60_000,
      maxAttempts: 3,
    });
    if (!claimed) throw new Error('该教师会话正在处理另一项请求，请稍后重试');
    await store.appendRunEvent(sessionId, workerId, {
      ts: Date.now(),
      attempt: claimed.attempt,
      type: resumed ? AGENT_SESSION_LIFECYCLE.sessionResumed : AGENT_SESSION_LIFECYCLE.sessionStart,
      data: { courseId },
    });
    return { sessionId, workerId, attempt: claimed.attempt, resumed };
  },

  async completeTeacherTurn(lease, output) {
    if (!lease) return;
    const store = await getAgentStore();
    if (!store) {
      await updateFileSession(lease.sessionId, (session) => {
        if (!session) throw new Error('教师会话不存在');
        appendFileEvent(session, 'message_end', output, lease.attempt);
        appendFileEvent(
          session,
          AGENT_SESSION_LIFECYCLE.checkpoint,
          { recoverable: true },
          lease.attempt,
        );
        session.meta.status = 'succeeded';
        session.meta.attempt = 0;
        return { session, result: undefined };
      });
      return;
    }
    await store.appendRunEvent(lease.sessionId, lease.workerId, {
      ts: Date.now(), attempt: lease.attempt, type: 'message_end', data: output,
    });
    await store.appendRunEvent(lease.sessionId, lease.workerId, {
      ts: Date.now(), attempt: lease.attempt, type: AGENT_SESSION_LIFECYCLE.checkpoint,
      data: { recoverable: true },
    });
    await store.finishSession(lease.sessionId, lease.workerId, {
      status: 'succeeded', expectedAttempt: lease.attempt, resetAttempt: true,
    });
  },

  async failTeacherTurn(lease, error) {
    if (!lease) return;
    const store = await getAgentStore();
    const message = error instanceof Error ? error.message : String(error);
    if (!store) {
      await updateFileSession(lease.sessionId, (session) => {
        if (!session) throw new Error('教师会话不存在');
        appendFileEvent(
          session,
          AGENT_SESSION_LIFECYCLE.sessionInterrupted,
          { error: message, recoverable: true },
          lease.attempt,
        );
        session.meta.status = 'failed';
        session.meta.error = message;
        return { session, result: undefined };
      }).catch(() => undefined);
      return;
    }
    await store.appendRunEvent(lease.sessionId, lease.workerId, {
      ts: Date.now(), attempt: lease.attempt, type: AGENT_SESSION_LIFECYCLE.sessionInterrupted,
      data: { error: message, recoverable: true },
    }).catch(() => undefined);
    await store.finishSession(lease.sessionId, lease.workerId, {
      status: 'failed', error: message, expectedAttempt: lease.attempt,
    }).catch(() => undefined);
  },

  async readTeacherEvents(sessionId, after = 0) {
    const store = await getAgentStore();
    if (store) return store.readEventsAfterForReplay(sessionId, after, 500).then((item) => item.events);
    return (await readFileSession(sessionId))?.events.filter((event) => event.id > after).slice(0, 500) ?? [];
  },

  async getTeacherSession(sessionId) {
    const store = await getAgentStore();
    return store ? store.getSession(sessionId) : (await readFileSession(sessionId))?.meta ?? null;
  },

  async listTeacherSessions(courseId, teacherId) {
    const store = await getAgentStore();
    const sessions = store
      ? await store.listSessionsByOwner(teacherId)
      : (await listFileSessions()).map((item) => item.meta);
    return sessions
      .filter((session) => session.stageId === courseId && session.origin === 'course-space')
      .sort((left, right) => right.updatedAt - left.updatedAt);
  },
};

export function getCourseSpaceStorageAdapter(): CourseSpaceStorageAdapter {
  return adapter;
}
