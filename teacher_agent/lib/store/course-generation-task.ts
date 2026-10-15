import { create } from 'zustand';
export type CourseGenerationTask = {
  id: string;
  courseId: string;
  title: string;
  status: 'running' | 'review' | 'completed' | 'failed';
  message: string;
  step: number;
  total: number;
  url?: string;
};
export const useCourseGenerationTask = create<{
  runtimeId: string | null;
  setRuntimeId: (id: string) => void;
  task: CourseGenerationTask | null;
  setTask: (task: CourseGenerationTask) => void;
}>((set) => ({
  runtimeId: null,
  setRuntimeId: (runtimeId) => set({ runtimeId }),
  task: null,
  setTask: (task) => set({ task }),
}));
export const isGenerationTaskActive = (task: CourseGenerationTask | null) =>
  Boolean(task && ['running', 'review'].includes(task.status));
