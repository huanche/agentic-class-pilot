import { nanoid } from 'nanoid';
import type { CourseSpaceRepository } from './repository';
import type { CourseMaterialRecord, CourseSpace, CreateCourseSpaceInput } from './types';

const STORAGE_KEY = 'ai-education-course-spaces-v1';

interface BrowserCourseSpaceState {
  schemaVersion: 1;
  courses: CourseSpace[];
}

function readState(): BrowserCourseSpaceState {
  if (typeof window === 'undefined') return { schemaVersion: 1, courses: [] };
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) || '',
    ) as BrowserCourseSpaceState;
    if (parsed.schemaVersion === 1 && Array.isArray(parsed.courses)) return parsed;
  } catch {
    // A malformed local draft must not prevent the teacher from opening the workspace.
  }
  return { schemaVersion: 1, courses: [] };
}

function writeState(state: BrowserCourseSpaceState): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export class BrowserCourseSpaceRepository implements CourseSpaceRepository {
  async listByTeacher(teacherId: string): Promise<CourseSpace[]> {
    return readState().courses.filter((course) => course.teacherId === teacherId);
  }

  async get(courseId: string): Promise<CourseSpace | undefined> {
    return readState().courses.find((course) => course.id === courseId);
  }

  async create(input: CreateCourseSpaceInput): Promise<CourseSpace> {
    const now = Date.now();
    const course: CourseSpace = {
      id: nanoid(12),
      teacherId: input.teacherId,
      title: input.title.trim(),
      subject: input.subject?.trim() || undefined,
      gradeBand: input.gradeBand?.trim() || undefined,
      term: input.term?.trim() || undefined,
      description: input.description?.trim() || undefined,
      status: 'draft',
      modules: [],
      materials: [],
      createdAt: now,
      updatedAt: now,
    };
    const state = readState();
    writeState({ ...state, courses: [course, ...state.courses] });
    return course;
  }

  async save(course: CourseSpace): Promise<void> {
    const state = readState();
    const next = state.courses.some((item) => item.id === course.id)
      ? state.courses.map((item) => (item.id === course.id ? course : item))
      : [course, ...state.courses];
    writeState({ ...state, courses: next });
  }

  async addMaterial(courseId: string, material: CourseMaterialRecord): Promise<CourseSpace> {
    const course = await this.get(courseId);
    if (!course) throw new Error(`Course space ${courseId} does not exist`);
    const next = { ...course, materials: [...course.materials, material], updatedAt: Date.now() };
    await this.save(next);
    return next;
  }
}
