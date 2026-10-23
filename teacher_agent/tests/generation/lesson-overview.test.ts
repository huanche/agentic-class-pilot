import { describe, expect, it } from 'vitest';
import type { GenerationSessionState } from '@/app/generation-preview/types';
import {
  lessonOverviewFromOutlines,
  sessionWithLessonOverview,
} from '@/lib/generation/lesson-overview';
import { readOutlineStream } from '@/lib/generation/outline-stream-client';

const outlines = [
  {
    id: 'p1',
    order: 1,
    type: 'slide' as const,
    title: '循环条件',
    description: '先判断再执行',
    keyPoints: ['边界条件'],
  },
];
const original: GenerationSessionState = {
  sessionId: 'fixture',
  currentStep: 'generating',
  previewPhase: 'review',
  requirements: { requirement: '原始资料与教师要求', targetDurationMinutes: 28 },
  pdfText: '原稿正文',
  sceneOutlines: outlines,
  conversionMode: 'faithful',
  sourceFingerprint: {
    algorithm: 'SHA-256',
    sha256: 'original',
    fileName: 'test.pptx',
    mimeType: 'application/test',
    byteLength: 12,
    lastModified: 1,
    pageCount: 5,
    importedAt: 1,
  },
};

describe('teacher lesson overview', () => {
  it('builds an editable overview from the actual page topics and learning points', () => {
    expect(lessonOverviewFromOutlines(outlines)).toContain('循环条件');
    expect(lessonOverviewFromOutlines(outlines)).toContain('边界条件');
    expect(lessonOverviewFromOutlines([])).toBe('');
  });
  it('replaces the previous revision intent, preserving source, mode, duration and old outline', () => {
    const first = sessionWithLessonOverview(original, '增加死循环案例');
    const second = sessionWithLessonOverview(first, '改为强调退出条件');
    expect(second.requirements.requirement).toContain('原始资料与教师要求');
    expect(second.requirements.requirement).toContain('改为强调退出条件');
    expect(second.requirements.requirement).not.toContain('增加死循环案例');
    expect(second.requirements.requirement).toContain('原始页序');
    expect(second.requirements.targetDurationMinutes).toBe(28);
    expect(second.sourceFingerprint).toBe(original.sourceFingerprint);
    expect(second.sceneOutlines).toBe(original.sceneOutlines);
    expect(second.pdfText).toBe(original.pdfText);
  });
  it('rejects an empty overview before issuing a model request', () => {
    expect(() => sessionWithLessonOverview(original, '  ')).toThrow('概述');
  });
});

describe('outline revision stream', () => {
  const response = (events: unknown[]) =>
    new Response(events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''));
  it('uses the completed replacement and retains the server-effective teaching mode', async () => {
    const result = await readOutlineStream(
      response([
        { type: 'outline', data: outlines[0] },
        { type: 'done', outlines, languageDirective: '中文', effectiveTaskEngineMode: true },
      ]),
    );
    expect(result.outlines).toEqual(outlines);
    expect(result.taskEngineMode).toBe(true);
  });
  it('does not replace a teacher outline with a partial stream after disconnection or model error', async () => {
    await expect(
      readOutlineStream(response([{ type: 'outline', data: outlines[0] }])),
    ).rejects.toThrow('连接中断');
    await expect(
      readOutlineStream(response([{ type: 'error', error: '服务暂不可用' }])),
    ).rejects.toThrow('服务暂不可用');
    await expect(readOutlineStream(response([{ type: 'done', outlines: [] }]))).rejects.toThrow(
      '原大纲已保留',
    );
  });
});
