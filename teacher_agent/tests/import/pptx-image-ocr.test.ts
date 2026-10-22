import { beforeEach, describe, expect, it, vi } from 'vitest';
import JSZip from 'jszip';
const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  files: new Map<string, Buffer>(),
  source: vi.fn(),
  image: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  COURSE_SPACES_DIR: '/workspace/ocr-tests',
  readCourseMaterialBytes: mocks.source,
}));
vi.mock('@/lib/server/pptx-page-image', () => ({ getPptxPageImage: mocks.image }));
vi.mock('@/lib/server/course-object-storage', () => ({
  isCourseObjectStorageEnabled: () => false,
}));
vi.mock('@/lib/server/provider-config', () => ({
  resolveApiKey: () => 'server-test-key',
  resolveASRApiKey: () => '',
  resolveImageApiKey: () => '',
}));
vi.mock('node:fs/promises', () => ({
  default: {
    readFile: vi.fn(async (name: string) => {
      if (mocks.files.has(name)) return mocks.files.get(name);
      throw Object.assign(new Error(), { code: 'ENOENT' });
    }),
    mkdir: vi.fn(),
    writeFile: vi.fn(async (name: string, data: Buffer) => mocks.files.set(name, data)),
    rename: vi.fn(async (from: string, to: string) => {
      mocks.files.set(to, mocks.files.get(from)!);
      mocks.files.delete(from);
    }),
  },
}));
import { recognizePptImage, recognizePptPage } from '@/lib/server/pptx-image-ocr';
import type { CourseMaterialRecord } from '@/lib/course-space/types';
const material = {
  sha256: 'unique-source-for-ocr-test',
  storageKey: 'original.pptx',
} as CourseMaterialRecord;

beforeEach(async () => {
  mocks.files.clear();
  mocks.fetch.mockReset();
  mocks.source.mockResolvedValue(await new JSZip().generateAsync({ type: 'nodebuffer' }));
  mocks.image.mockResolvedValue(Buffer.from('source-image'));
  vi.stubGlobal('fetch', mocks.fetch);
});
describe('server image-only PPT OCR', () => {
  it('shares duplicate page requests and persists results without uploading or modifying the original', async () => {
    mocks.fetch.mockResolvedValue(
      Response.json({
        choices: [
          { finish_reason: 'stop', message: { content: '第2章 信号分析\n抽样频率 f_s = 2f_H' } },
        ],
      }),
    );
    const [first, same] = await Promise.all([
      recognizePptPage(material, 1),
      recognizePptPage(material, 1),
    ]);
    expect(first).toEqual(same);
    expect(first.content).toContain('f_s = 2f_H');
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    expect(await recognizePptPage(material, 1)).toEqual(first);
    expect(mocks.fetch).toHaveBeenCalledTimes(1);
    const [, request] = mocks.fetch.mock.calls[0];
    expect(request.headers.authorization).toBe('Bearer server-test-key');
    expect(JSON.parse(request.body).model).toBe('qwen-vl-ocr');
  });
  it('does not accept truncated or blank OCR as a completed page', async () => {
    mocks.fetch.mockResolvedValueOnce(
      Response.json({ choices: [{ finish_reason: 'length', message: { content: 'partial' } }] }),
    );
    await expect(recognizePptImage(Buffer.from('image'))).rejects.toThrow('不完整');
    mocks.fetch.mockResolvedValueOnce(
      Response.json({ choices: [{ finish_reason: 'stop', message: { content: ' ' } }] }),
    );
    await expect(recognizePptImage(Buffer.from('image'))).rejects.toThrow('未识别到');
  });
  it('supports cancellation and never exposes upstream error payloads', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(recognizePptPage(material, 2, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    });
    expect(mocks.fetch).not.toHaveBeenCalled();
    mocks.fetch.mockResolvedValueOnce(
      Response.json({ error: { message: 'upstream-private-information' } }, { status: 429 }),
    );
    await expect(recognizePptImage(Buffer.from('image'))).rejects.toThrow('（429）');
  });
});
