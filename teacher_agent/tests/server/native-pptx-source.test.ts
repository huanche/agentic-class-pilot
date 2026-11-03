import { describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import JSZip from 'jszip';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
const state = vi.hoisted(() => ({ bytes: Buffer.alloc(0) as Buffer }));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: async () => ({ materials: [{ id: 'source', name: 'original.pptx' }] }),
  readCourseMaterialBytes: async () => state.bytes,
}));
vi.mock('@/lib/server/classroom-storage', () => ({
  CLASSROOMS_DIR: path.join(process.cwd(), '.runtime', 'native-snapshot-tests'),
}));
import { prepareNativePptxSource } from '@/lib/server/native-pptx-source';
describe('immutable native PPTX source snapshot', () => {
  it('verifies the exact material, retains source page identities and rejects changed sources', async () => {
    const zip = new JSZip();
    const ns = 'http://schemas.openxmlformats.org/presentationml/2006/main';
    zip.file(
      'ppt/presentation.xml',
      `<p:presentation xmlns:p="${ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="1" r:id="rId1"/><p:sldId id="2" r:id="rId2"/><p:sldId id="3" r:id="rId3"/></p:sldIdLst></p:presentation>`,
    );
    zip.file('ppt/slides/slide1.xml', `<p:sld xmlns:p="${ns}"/>`);
    zip.file('ppt/slides/slide2.xml', `<p:sld xmlns:p="${ns}"/>`);
    zip.file('ppt/slides/slide3.xml', `<p:sld xmlns:p="${ns}"/>`);
    zip.file(
      'ppt/_rels/presentation.xml.rels',
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        [1, 2, 3]
          .map((i) => `<Relationship Id="rId${i}" Target="slides/slide${i}.xml"/>`)
          .join('') +
        '</Relationships>',
    );
    state.bytes = await zip.generateAsync({ type: 'nodebuffer' });
    const sha = createHash('sha256').update(state.bytes).digest('hex');
    const input = {
      stage: { id: 'native_snapshot_test' },
      preferImportedCanvas: true,
      nativePptxSource: { materialId: 'source', sha256: sha },
      outlines: [
        { id: 'third', order: 1, type: 'slide', sourceSlideOriginalIndex: 2 },
        { id: 'first', order: 2, type: 'slide', sourceSlideOriginalIndex: 0 },
      ],
    } as unknown as BackgroundCoursewareInput;
    await prepareNativePptxSource(input, 'course');
    expect(input.stage.nativePptx?.pages).toEqual({ third: 3, first: 1 });
    const saved = await fs.readFile(
      path.join(
        process.cwd(),
        '.runtime/native-snapshot-tests/native_snapshot_test/native/source.pptx',
      ),
    );
    expect(saved.equals(state.bytes)).toBe(true);
    expect(input.stage.nativePptx?.sourceSha256).toBe(sha);
    input.nativePptxSource!.sha256 = '0'.repeat(64);
    await expect(prepareNativePptxSource(input, 'course')).rejects.toThrow('来源版本已变化');
    expect(input.stage.nativePptx).toBeUndefined();
  });
});
