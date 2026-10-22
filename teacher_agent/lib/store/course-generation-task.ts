import { create } from 'zustand';
export type CourseGenerationTask = {
  id: string;
  courseId: string;
  title: string;
  status: 'running' | 'review' | 'completed' | 'failed' | 'cancelled';
  message: string;
  step: number;
  total: number;
  url?: string;
  serverJobId?: string;
};
const cancelHandlers = new Map<string, () => void | Promise<void>>();
const cancellations = new Map<string, Promise<void>>();
const cancelledIds = new Set<string>();
export const useCourseGenerationTask = create<{
  runtimeId: string | null;
  setRuntimeId: (id: string) => void;
  task: CourseGenerationTask | null;
  setTask: (task: CourseGenerationTask) => void;
  registerCancelHandler: (id: string, cancel: () => void | Promise<void>) => () => void;
  cancelTask: (id: string) => Promise<void>;
}>((set, get) => ({
  runtimeId: null,
  setRuntimeId: (runtimeId) => set({ runtimeId }),
  task: null,
  setTask: (task) => {
    // Late progress from a stopped runtime must not revive it or replace a new task.
    if (!cancelledIds.has(task.id)) set({ task });
  },
  registerCancelHandler: (id, cancel) => {
    cancelHandlers.set(id, cancel);
    return () => {
      if (cancelHandlers.get(id) === cancel) cancelHandlers.delete(id);
    };
  },
  cancelTask: (id) => {
    const pending = cancellations.get(id);
    if (pending) return pending;
    const task = get().task;
    if (task?.id !== id || task.serverJobId || !isGenerationTaskActive(task))
      return Promise.resolve();
    const cancel = Promise.resolve()
      .then(async () => {
        await cancelHandlers.get(id)?.();
        cancelledIds.add(id);
        if (typeof sessionStorage !== 'undefined') {
          const saved = sessionStorage.getItem('generationSession');
          if (saved) {
            try {
              if (JSON.parse(saved).sessionId === id)
                sessionStorage.removeItem('generationSession');
            } catch {
              // A different/invalid saved session is not owned by this task.
            }
          }
        }
        set((state) => ({
          ...(state.task?.id === id
            ? { task: { ...state.task, status: 'cancelled', message: '已取消生成' } }
            : {}),
          ...(state.runtimeId === id ? { runtimeId: null } : {}),
        }));
      })
      .finally(() => cancellations.delete(id));
    cancellations.set(id, cancel);
    return cancel;
  },
}));
export const isGenerationTaskActive = (task: CourseGenerationTask | null) =>
  Boolean(task && ['running', 'review'].includes(task.status));
