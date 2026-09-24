export declare const INTEGRATION_PROTOCOL_VERSION: "1.0";
export type IntegrationSource = 'saas-host' | 'teacher-workspace' | 'classroom-player';
export type CourseScope = {
    type: 'course';
} | {
    type: 'module';
    moduleId: string;
} | {
    type: 'lesson';
    lessonId: string;
};
export interface IntegrationEnvelope<TType extends string = string, TPayload = unknown> {
    version: typeof INTEGRATION_PROTOCOL_VERSION;
    id: string;
    type: TType;
    source: IntegrationSource;
    timestamp: number;
    payload: TPayload;
}
export type HostToTeacherMessage = IntegrationEnvelope<'HOST_CONTEXT', {
    tenantId: string;
    userId: string;
    courseId: string;
    scope?: CourseScope;
    locale?: string;
    theme?: 'light' | 'dark' | 'system';
    permissions: string[];
}> | IntegrationEnvelope<'HOST_SCOPE_CHANGED', {
    courseId: string;
    scope: CourseScope;
}> | IntegrationEnvelope<'HOST_APPEARANCE_CHANGED', {
    locale?: string;
    theme?: 'light' | 'dark' | 'system';
}> | IntegrationEnvelope<'HOST_OPEN_FEATURE', {
    feature: 'teacher-workspace' | 'knowledge-graph' | 'artifact-review' | 'classroom';
    resourceId?: string;
}>;
export type TeacherToHostMessage = IntegrationEnvelope<'TEACHER_WORKSPACE_READY', {
    capabilities: string[];
    courseId?: string;
}> | IntegrationEnvelope<'WORK_SCOPE_CHANGED', {
    courseId: string;
    scope: CourseScope;
    displayPath: string;
}> | IntegrationEnvelope<'GENERATION_JOB_CREATED', {
    courseId: string;
    jobId: string;
    artifactType: string;
    scope: CourseScope;
}> | IntegrationEnvelope<'GENERATION_JOB_PROGRESS', {
    courseId: string;
    jobId: string;
    phase: string;
    progress: number;
    message?: string;
}> | IntegrationEnvelope<'ARTIFACT_CREATED', {
    courseId: string;
    artifactId: string;
    artifactType: string;
    classroomId?: string;
    status: string;
}> | IntegrationEnvelope<'OPEN_CLASSROOM', {
    courseId: string;
    classroomId: string;
    mode: 'edit' | 'preview' | 'play' | 'review';
}> | IntegrationEnvelope<'KNOWLEDGE_GRAPH_UPDATED', {
    courseId: string;
    version: number;
    status: string;
}> | IntegrationEnvelope<'WORKSPACE_ERROR', {
    code: string;
    message: string;
    recoverable: boolean;
    resourceId?: string;
}>;
