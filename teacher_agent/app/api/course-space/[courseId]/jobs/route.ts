import { after, type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { buildRequestOrigin } from '@/lib/server/classroom-storage';
import { runCourseArtifactJob } from '@/lib/server/course-artifact-runner';
import {
  listCourseJobs,
  markStaleCourseJobsFailed,
  readServerCourse,
  saveCourseJob,
} from '@/lib/server/course-space-storage';
import type { CourseArtifactJob, CourseArtifactType } from '@/lib/course-space/types';

const artifactTypes: CourseArtifactType[] = [
  'course-outline', 'module-plan', 'lesson-courseware', 'narration',
  'exercise-set', 'assessment-rubric', 'pbl-project',
];

export const maxDuration = 30;

function sameScope(left: CourseArtifactJob['scope'], right: CourseArtifactJob['scope']) {
  if (left.type !== right.type) return false;
  if (left.type === 'course' && right.type === 'course') return true;
  if (left.type === 'module' && right.type === 'module') return left.moduleId === right.moduleId;
  if (left.type === 'lesson' && right.type === 'lesson') return left.lessonId === right.lessonId;
  return false;
}

export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const body = (await req.json()) as {
    scope?: CourseArtifactJob['scope'];
    artifactTypes?: CourseArtifactType[];
  };
  const selected = [...new Set(body.artifactTypes ?? [])].filter((type) => artifactTypes.includes(type));
  if (selected.length === 0) return apiError('MISSING_REQUIRED_FIELD', 400, '请选择要生成的教学产物');
  const scope = body.scope ?? { type: 'course' as const };
  const scopeExists = scope.type === 'course'
    || (scope.type === 'module' && course.modules.some((item) => item.id === scope.moduleId))
    || (scope.type === 'lesson' && course.modules.some((item) => item.lessons.some((lesson) => lesson.id === scope.lessonId)));
  if (!scopeExists) return apiError('INVALID_REQUEST', 400, '生成范围不属于当前课程');
  if (!course.materials.some((item) => item.status === 'ready')) {
    return apiError('INVALID_REQUEST', 409, '请先解析至少一份课程材料');
  }
  const existingJobs = await listCourseJobs(courseId);
  const activeJobs = existingJobs.filter(
    (job) =>
      selected.includes(job.artifactType) &&
      sameScope(job.scope, scope) &&
      (job.status === 'queued' || job.status === 'running'),
  );
  const staleJobs = await markStaleCourseJobsFailed(activeJobs);
  const liveJob = activeJobs.find((job) => !staleJobs.some((stale) => stale.id === job.id));
  if (liveJob) {
    return apiError(
      'INVALID_REQUEST',
      409,
      `已有相同范围的${liveJob.artifactType === 'lesson-courseware' ? '课件' : '教学产物'}任务正在生成，请勿重复提交`,
    );
  }
  const now = Date.now();
  const jobs = await Promise.all(selected.map((artifactType) => saveCourseJob({
    id: nanoid(14), teacherId: course.teacherId, courseId,
    scope, artifactType,
    status: 'queued', progress: 0, message: '等待生成', createdAt: now, updatedAt: now,
  })));
  const baseUrl = buildRequestOrigin(req);
  after(() => Promise.all(jobs.map((job) => runCourseArtifactJob(job.id, baseUrl))).then(() => undefined));
  return apiSuccess({ jobs }, 202);
}
