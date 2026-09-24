import { mkdtemp, readFile, rm } from 'fs/promises';
import { tmpdir } from 'os';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { splitIntoPageChunks } from '@/lib/server/course-material-parser';
import JSZip from 'jszip';
import { extractPptxText } from '@/lib/server/pptx-text-extractor';

let testDir = '';

beforeEach(async () => {
  testDir = await mkdtemp(path.join(tmpdir(), 'course-space-test-'));
  process.env.COURSE_SPACES_DATA_DIR = testDir;
  vi.resetModules();
});

afterEach(async () => {
  delete process.env.COURSE_SPACES_DATA_DIR;
  if (testDir) await rm(testDir, { recursive: true, force: true });
});

describe('server course space', () => {
  it('persists courses and source materials with a SHA-256 fingerprint', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const course = await storage.createServerCourse({ teacherId: 'teacher-a', title: '信号与系统' });
    const material = await storage.storeCourseMaterial({
      courseId: course.id,
      teacherId: course.teacherId,
      fileName: 'lesson.txt',
      mimeType: 'text/plain',
      bytes: Buffer.from('page one'),
    });
    const restored = await storage.readServerCourse(course.id);
    expect(restored?.materials[0].id).toBe(material.id);
    expect(material.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(await readFile(path.join(testDir, 'materials', material.id, 'source.txt'), 'utf8')).toBe('page one');
  });

  it('keeps extractor page numbers and formula text in knowledge chunks', () => {
    const chunks = splitIntoPageChunks('material-1', {
      text: 'fallback',
      images: [],
      layout: [
        { page: 2, type: 'title', content: '第二页' },
        { page: 1, type: 'text', content: '第一页内容' },
      ],
      formulas: [{ page: 2, latex: 'P=UI' }],
      metadata: { pageCount: 2 },
    });
    expect(chunks.map((chunk) => chunk.page)).toEqual([1, 2]);
    expect(chunks[1].text).toContain('[公式] P=UI');
  });

  it('extracts PPTX slide text locally without requiring MinerU', async () => {
    const zip = new JSZip();
    zip.file('ppt/slides/slide1.xml', '<p:sld><a:t>课程标题</a:t><a:t>第一知识点</a:t></p:sld>');
    zip.file('ppt/slides/slide2.xml', '<p:sld><a:t>第二页</a:t><a:t>P=UI</a:t></p:sld>');
    const parsed = await extractPptxText(Buffer.from(await zip.generateAsync({ type: 'uint8array' })), 'demo.pptx');
    expect(parsed.metadata?.pageCount).toBe(2);
    expect(parsed.layout?.find((item) => item.page === 2)?.content).toBe('第二页');
    expect(parsed.text).toContain('第一知识点');
  });
});
