import { getCourseDatabasePool } from '@/lib/server/course-space-database';

export type StudentLearningSummary = {
  studentId: string;
  /** 已学课时：distinct classroom_id，天然抗刷新产生的僵尸会话。 */
  learnedLessons: number;
  sessionCount: number;
  endedCount: number;
  eventCount: number;
  reportCount: number;
  /** 最近活跃 epoch ms；取会话活跃与学习事件时间的较大者。0 = 从未活跃。 */
  lastActiveAt: number;
};

type SessionAggregateRow = {
  user_id: string;
  learned: string;
  sessions: string;
  ended: string;
  last_active: string | null;
};

type CountRow = { user_id: string; total: string; last_at: Date | string | null };

function toMillis(value: Date | string | null): number {
  if (value instanceof Date) return value.getTime();
  if (typeof value === 'string') {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

/**
 * Real-time per-student aggregates for one course, read straight from the
 * student schema (platform-owned; the teacher role holds SELECT-only grants
 * there). This replaces the event-driven classStudents mirror that arrived
 * via PUT /api/classes/{id}/students — the roster supplies the authorized
 * student ids, so no extra authorization surface is needed here.
 */
export async function fetchStudentLearningSummaries(
  platformCourseId: string,
  studentIds: string[],
): Promise<Map<string, StudentLearningSummary>> {
  const summaries = new Map<string, StudentLearningSummary>();
  const pool = getCourseDatabasePool();
  if (!pool || studentIds.length === 0) return summaries;

  const sessions = await pool.query<SessionAggregateRow>(
    `SELECT user_id,
            count(DISTINCT classroom_id) AS learned,
            count(*) AS sessions,
            count(*) FILTER (WHERE ended_at IS NOT NULL) AS ended,
            max(last_active_at) AS last_active
       FROM student.student_sessions
      WHERE course_id = $1 AND user_id = ANY($2)
      GROUP BY user_id`,
    [platformCourseId, studentIds],
  );
  const events = await pool.query<CountRow>(
    `SELECT user_id, count(*) AS total, max(created_at) AS last_at
       FROM student.learning_events
      WHERE course_id = $1 AND user_id = ANY($2)
      GROUP BY user_id`,
    [platformCourseId, studentIds],
  );
  const reports = await pool.query<CountRow>(
    `SELECT user_id, count(*) AS total, max(created_at) AS last_at
       FROM student.after_class_reports
      WHERE course_id = $1 AND user_id = ANY($2)
      GROUP BY user_id`,
    [platformCourseId, studentIds],
  );

  for (const row of sessions.rows) {
    summaries.set(row.user_id, {
      studentId: row.user_id,
      learnedLessons: Number(row.learned),
      sessionCount: Number(row.sessions),
      endedCount: Number(row.ended),
      eventCount: 0,
      reportCount: 0,
      lastActiveAt: toMillis(row.last_active),
    });
  }
  for (const row of events.rows) {
    const entry = summaries.get(row.user_id) ?? {
      studentId: row.user_id,
      learnedLessons: 0,
      sessionCount: 0,
      endedCount: 0,
      eventCount: 0,
      reportCount: 0,
      lastActiveAt: 0,
    };
    entry.eventCount = Number(row.total);
    entry.lastActiveAt = Math.max(entry.lastActiveAt, toMillis(row.last_at));
    summaries.set(row.user_id, entry);
  }
  for (const row of reports.rows) {
    const entry = summaries.get(row.user_id) ?? {
      studentId: row.user_id,
      learnedLessons: 0,
      sessionCount: 0,
      endedCount: 0,
      eventCount: 0,
      reportCount: 0,
      lastActiveAt: 0,
    };
    entry.reportCount = Number(row.total);
    entry.lastActiveAt = Math.max(entry.lastActiveAt, toMillis(row.last_at));
    summaries.set(row.user_id, entry);
  }
  return summaries;
}
