'use client';
import { useEffect } from 'react';
import { useCourseGenerationTask } from '@/lib/store/course-generation-task';
import { usePathname } from 'next/navigation';
import dynamic from 'next/dynamic';
import type { CourseArtifactJob } from '@/lib/course-space/types';
const Preview = dynamic(() => import('@/app/generation-preview/preview-runtime'), { ssr: false });
export function GenerationTaskHost() {
  const pathname = usePathname();
  const runtimeId = useCourseGenerationTask((state) => state.runtimeId);
  const task = useCourseGenerationTask((state) => state.task);
  useEffect(() => {
    if (!task?.serverJobId || task.status !== 'running') return;
    let alive = true;
    const poll = async () => {
      try {
        const response = await fetch(`/api/course-space/jobs/${task.serverJobId}`, {
          cache: 'no-store',
        });
        if (!response.ok) return;
        const { job } = (await response.json()) as { job: CourseArtifactJob };
        if (!alive || useCourseGenerationTask.getState().task?.id !== task.id) return;
        useCourseGenerationTask.getState().setTask({
          ...task,
          status:
            job.status === 'cancelled'
              ? 'cancelled'
              : job.status === 'failed'
                ? 'failed'
                : job.status === 'review' || job.status === 'approved'
                  ? 'completed'
                  : 'running',
          message: job.message,
          step: job.backgroundGeneration?.completedPages ?? task.step,
          total: job.backgroundGeneration?.totalPages ?? task.total,
        });
      } catch {
        /* A temporary network failure does not cancel the server task. */
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 2500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [task?.serverJobId, task?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const saved = sessionStorage.getItem('generationSession');
    if (!saved) {
      if (pathname === '/generation-preview')
        useCourseGenerationTask.getState().setRuntimeId('missing-session');
      return;
    }
    try {
      const session = JSON.parse(saved);
      if (pathname === '/generation-preview' || session.courseSpaceContext)
        useCourseGenerationTask.getState().setRuntimeId(session.sessionId || 'legacy');
    } catch {
      /* Invalid sessions are handled by the preview. */
    }
  }, [pathname]);
  if (!runtimeId) return null;
  return (
    <div hidden={pathname !== '/generation-preview'}>
      <Preview key={runtimeId} />
    </div>
  );
}
