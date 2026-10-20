// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import PptxGenJS from 'pptxgenjs';
import { importPptx } from '@openmaic/importer';
import { buildImportedPptDraft } from '@/lib/import/pptx-course';

describe('PPTX import to content review', () => {
  it('sends image-only pages with empty placeholder text to OCR', () => {
    const draft = buildImportedPptDraft([
      {
        id: 'image-page',
        elements: [
          { type: 'text', content: '<p>&nbsp;</p>' },
          { type: 'image', src: 'data:image/jpeg;base64,test' },
        ],
      } as never,
    ]);
    expect(draft.slides[0]).toMatchObject({ title: '第 1 页', content: '', imageOcr: 'pending' });
  });
  it('reads the original shape text without rewriting the uploaded PPTX', async () => {
    const ppt = new PptxGenJS();
    ppt.layout = 'LAYOUT_WIDE';
    const page = ppt.addSlide();
    // A filled text container is intentionally imported as a shape to retain
    // its visual frame. The review must still read the text within it.
    page.addText('Python 变量与类型', {
      x: 0.5,
      y: 0.5,
      w: 10,
      h: 0.8,
      fontSize: 28,
      fill: { color: 'EEEEEE' },
    });
    page.addText('变量用于保存数据。\nage = 18', {
      x: 0.5,
      y: 1.5,
      w: 10,
      h: 2,
      fontSize: 20,
      fill: { color: 'FFFFFF' },
    });
    const bytes = (await ppt.write({ outputType: 'arraybuffer' })) as ArrayBuffer;
    const slides = await importPptx(bytes);
    expect(
      slides[0].elements.some((element) => element.type === 'shape' && element.text?.content),
    ).toBe(true);

    const draft = buildImportedPptDraft(slides);
    expect(draft.slides[0]).toMatchObject({
      title: 'Python 变量与类型',
      content: '变量用于保存数据。 age = 18',
    });
    expect(slides[0].elements.some((element) => element.type === 'shape')).toBe(true);
  });
});
