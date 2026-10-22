import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
const mocks = vi.hoisted(() => ({ course: vi.fn(), recognize: vi.fn(), preview: vi.fn() }));
vi.mock('@/lib/server/course-space-storage', () => ({ readServerCourse: mocks.course }));
vi.mock('@/lib/server/pptx-image-ocr', () => ({
  recognizePptPage: mocks.recognize,
  readPptPagePreview: mocks.preview,
}));
import {
  GET,
  POST,
} from '@/app/api/course-space/[courseId]/materials/[materialId]/ocr/[page]/route';
const context = (page = '1') => ({
  params: Promise.resolve({ courseId: 'course', materialId: 'material', page }),
});
function request(user?: string) {
  return new NextRequest('http://localhost/api/ocr', {
    headers: user ? { 'x-platform-user-id': user } : {},
  });
}
afterEach(() => vi.unstubAllEnvs());
describe('PPT OCR route', () => {
  it('requires the authenticated course owner before making any OCR call', async () => {
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
    expect((await POST(request(), context())).status).toBe(401);
    mocks.course.mockResolvedValue({
      teacherId: 'owner',
      materials: [{ id: 'material', name: 'lesson.pptx', pageCount: 77 }],
    });
    expect((await POST(request('other-teacher'), context())).status).toBe(404);
    expect(mocks.recognize).not.toHaveBeenCalled();
    expect((await POST(request('owner'), context('78'))).status).toBe(400);
    expect((await POST(request('owner'), context('../1'))).status).toBe(400);
    mocks.recognize.mockResolvedValue({ title: '信号', content: '随机信号', model: 'test' });
    const response = await POST(request('owner'), context());
    expect(await response.json()).toMatchObject({ success: true, result: { content: '随机信号' } });
    mocks.preview.mockResolvedValue(Buffer.from('jpeg'));
    expect((await GET(request('owner'), context())).headers.get('content-type')).toBe('image/jpeg');
  });
});
