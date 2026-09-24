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
];
export function isTeacherPermission(value) {
    return typeof value === 'string' && teacherPermissions.includes(value);
}
