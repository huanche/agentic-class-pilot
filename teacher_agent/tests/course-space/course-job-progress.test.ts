import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { CourseJobProgress } from '@/components/course-space/course-job-progress';
import type { CourseArtifactJob } from '@/lib/course-space';

function markup(status: CourseArtifactJob['status'], extra = {}) {
  return renderToStaticMarkup(
    createElement(CourseJobProgress, {
      job: {
        artifactType: 'lesson-courseware',
        status,
        progress: 40,
        message: '等待审核',
        backgroundGeneration: { completedPages: 2, totalPages: 7, classroomId: 'class' },
        ...extra,
      } as CourseArtifactJob,
      cancelling: false,
      retrying: false,
      onCancel() {},
      onRetry() {},
      onView() {},
    }),
  );
}
describe('courseware task progress', () => {
  it.each(['review', 'approved'] as const)(
    'shows completed %s jobs without an extra review/output step',
    (status) => {
      const html = markup(status);
      expect(html).toContain('课件已生成');
      expect(html).toContain('生成完成');
      expect(html).toContain('100%');
      expect(html).toContain('返回工作区查看');
      expect(html).not.toMatch(/审核|可视化|取消未完成|重试未完成/);
    },
  );
  it('keeps cancellation and current progress while running', () => {
    const html = markup('running', { message: '生成配音' });
    expect(html).toContain('40%');
    expect(html).toContain('取消未完成任务');
    expect(html).not.toContain('重试未完成页面');
  });
  it('offers a missing-page retry and the actual failure details', () => {
    const html = markup('failed', { error: '讲解校验失败' });
    expect(html).toContain('讲解校验失败');
    expect(html).toContain('重试未完成页面');
    expect(html).not.toContain('取消未完成任务');
  });
  it('leaves cancelled jobs stopped', () => {
    const html = markup('cancelled');
    expect(html).toContain('任务已取消');
    expect(html).not.toMatch(/取消未完成任务|重试未完成页面/);
  });
});
