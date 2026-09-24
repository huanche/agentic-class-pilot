import type { CourseMaterialRecord, CourseSpace, CreateCourseSpaceInput } from './types';
import type { CourseSpaceRepository } from './repository';

async function json<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { success?: boolean; error?: string };
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

export class ApiCourseSpaceRepository implements CourseSpaceRepository {
  async listByTeacher(teacherId: string): Promise<CourseSpace[]> {
    const payload = await json<{ courses: CourseSpace[] }>(
      await fetch(`/api/course-space?teacherId=${encodeURIComponent(teacherId)}`, { cache: 'no-store' }),
    );
    return payload.courses;
  }

  async get(courseId: string): Promise<CourseSpace | undefined> {
    const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
    if (response.status === 404) return undefined;
    return (await json<{ course: CourseSpace }>(response)).course;
  }

  async create(input: CreateCourseSpaceInput): Promise<CourseSpace> {
    return (await json<{ course: CourseSpace }>(await fetch('/api/course-space', {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(input),
    }))).course;
  }

  async save(course: CourseSpace): Promise<void> {
    await json(await fetch(`/api/course-space/${course.id}`, {
      method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(course),
    }));
  }

  async addMaterial(_courseId: string, _material: CourseMaterialRecord): Promise<CourseSpace> {
    throw new Error('服务端材料必须通过 multipart 上传接口写入');
  }
}
