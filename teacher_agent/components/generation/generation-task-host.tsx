'use client';
import { useEffect } from 'react';
import { useCourseGenerationTask } from '@/lib/store/course-generation-task';
import { usePathname } from 'next/navigation';
import dynamic from 'next/dynamic';
const Preview = dynamic(() => import('@/app/generation-preview/preview-runtime'), { ssr: false });
export function GenerationTaskHost() {
  const pathname = usePathname();
  const runtimeId = useCourseGenerationTask((state) => state.runtimeId);
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
