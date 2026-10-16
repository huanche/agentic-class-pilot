import { describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const mocks = vi.hoisted(() => ({
  tts: vi.fn(async () => ({ generated: 1, failed: 0, skipped: 0 })),
  persist: vi.fn(async () => {}),
}));
vi.mock('@/lib/server/classroom-media-generation', () => ({
  generateTTSForClassroom: mocks.tts,
}));
vi.mock('@/lib/server/classroom-storage', () => ({
  buildRequestOrigin: () => 'http://localhost',
  isValidClassroomId: () => true,
  readClassroom: async () => ({
    id: 'class',
    stage: { languageDirective: '使用简体中文讲解' },
    scenes: [],
  }),
  persistClassroom: mocks.persist,
}));
vi.mock('@/lib/server/course-space-database', () => ({
  readClassroomBindingFromDatabase: async () => ({ courseId: 'course' }),
}));
vi.mock('@/lib/server/platform-user-model-config', () => ({
  getPlatformUserModelConfigForRequest: async () => null,
}));
import { POST } from '@/app/api/course-space/[courseId]/classrooms/[classroomId]/narration/route';

describe('classroom narration regeneration language', () => {
  it('uses the stored course language when regenerating audio', async () => {
    const response = await POST(
      new NextRequest('http://localhost/api/narration', { method: 'POST' }),
      {
        params: Promise.resolve({ courseId: 'course', classroomId: 'class' }),
      },
    );
    expect(response.status).toBe(200);
    expect(mocks.tts).toHaveBeenCalledWith([], 'class', 'http://localhost', undefined, {
      languageDirective: '使用简体中文讲解',
    });
    expect(mocks.persist).toHaveBeenCalledOnce();
  });
});
