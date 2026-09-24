export declare const teacherPermissions: readonly ["course.read", "course.structure.write", "material.read", "material.upload", "artifact.generate", "artifact.edit", "artifact.review", "artifact.publish", "knowledge_graph.generate", "knowledge_graph.review", "knowledge_graph.publish", "classroom.edit", "classroom.play"];
export type TeacherPermission = (typeof teacherPermissions)[number];
export declare function isTeacherPermission(value: unknown): value is TeacherPermission;
