import { readFileSync } from 'node:fs';
import JSZip from 'jszip';
import { describe, expect, it } from 'vitest';
import { extractWordText } from '@/lib/server/word-text-extractor';

export async function wordDocument(body: string): Promise<Buffer> {
  const zip = new JSZip();
  zip.file(
    '[Content_Types].xml',
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
  );
  zip.file(
    'word/document.xml',
    `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}</w:body></w:document>`,
  );
  return zip.generateAsync({ type: 'nodebuffer' });
}

describe('local Word extraction', () => {
  it('reads a real binary DOC with Unicode and excludes deleted review text', async () => {
    const buffer = readFileSync(new URL('../fixtures/word/legacy-text.doc', import.meta.url));
    const result = await extractWordText(buffer, '教学进度.doc');
    expect(result.text).toContain('This is a test of reviewing');
    expect(result.text).toContain('😀 ∀');
    expect(result.metadata?.parser).toBe('local-word');
    expect(result.layout?.[0].content).toContain('This text has been inserted');
  });

  it('preserves Chinese paragraphs, XML entities and table cells from DOCX', async () => {
    const buffer = await wordDocument(
      '<w:p><w:r><w:t>第一章 教学目标 &amp; 知识点</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>课程名称</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>现代交换原理</w:t></w:r></w:p></w:tc></w:tr></w:tbl>',
    );
    const result = await extractWordText(buffer, '教学计划.docx');
    expect(result.text).toContain('教学目标 & 知识点');
    expect(result.text).toContain('课程名称');
    expect(result.text).toContain('现代交换原理');
    expect(result.images).toEqual([]);
  });

  it('detects DOCX contents even when the file has a DOC extension', async () => {
    const buffer = await wordDocument('<w:p><w:r><w:t>另存文件正文</w:t></w:r></w:p>');
    expect((await extractWordText(buffer, '课程.doc')).text).toContain('另存文件正文');
  });

  it('rejects corrupt or empty documents with a useful Chinese error', async () => {
    await expect(extractWordText(Buffer.from('not a word document'), 'broken.doc')).rejects.toThrow(
      '另存为 .docx',
    );
    await expect(extractWordText(await wordDocument('<w:p/>'), 'empty.docx')).rejects.toThrow(
      '未提取到可用文字',
    );
  });
});
