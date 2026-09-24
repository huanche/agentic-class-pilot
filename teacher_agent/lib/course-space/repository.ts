import type { CourseMaterialRecord, CourseSpace, CreateCourseSpaceInput } from './types';

export interface CourseSpaceRepository {
  listByTeacher(teacherId: string): Promise<CourseSpace[]>;
  get(courseId: string): Promise<CourseSpace | undefined>;
  create(input: CreateCourseSpaceInput): Promise<CourseSpace>;
  save(course: CourseSpace): Promise<void>;
  addMaterial(courseId: string, material: CourseMaterialRecord): Promise<CourseSpace>;
}
