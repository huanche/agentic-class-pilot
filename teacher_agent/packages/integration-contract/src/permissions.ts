export const teacherPermissions = [
  'course.read',
  'course.structure.write',
  'material.read',
  'material.upload',
  'artifact.generate',
  'artifact.edit',
  'artifact.review',
  'artifact.publish',
  'knowledge_graph.generate',
  'knowledge_graph.review',
  'knowledge_graph.publish',
  'classroom.edit',
  'classroom.play',
] as const;

export type TeacherPermission = (typeof teacherPermissions)[number];

export function isTeacherPermission(value: unknown): value is TeacherPermission {
  return typeof value === 'string' && teacherPermissions.includes(value as TeacherPermission);
}
