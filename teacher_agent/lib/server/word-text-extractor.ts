import WordExtractor from 'word-extractor';
import type { ParsedPdfContent } from '@/lib/types/pdf';

/** Extract Word text locally. Pagination follows explicit breaks, not rendered Office pages. */
export async function extractWordText(buffer: Buffer, fileName: string): Promise<ParsedPdfContent> {
  let document;
  try {
    document = await new WordExtractor().extract(buffer);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/encrypt|password/i.test(message)) {
      throw new Error('Word 材料已加密，请解除密码保护后重新上传');
    }
    throw new Error('Word 材料无法读取，请确认文件未损坏，并使用 Word 另存为 .docx 后重试');
  }
  // Body includes table text. Include teaching content in text boxes and notes,
  // but exclude revision comments and repeated headers/footers.
  const sections = [
    document.getBody(),
    document.getTextboxes({ includeHeadersAndFooters: false }),
    document.getFootnotes(),
    document.getEndnotes(),
  ].filter((text) => text.trim());
  const text = sections
    .join('\n\n')
    .replace(/\u0000/g, '')
    .replace(/\r\n?/g, '\n')
    .trim();
  if (!text)
    throw new Error('Word 材料中未提取到可用文字；扫描图片或图片公式需要配置 OCR 解析服务');
  const pages = text
    .split(/\f/)
    .map((part) => part.trim())
    .filter(Boolean);
  return {
    text: pages.join('\n\n<!-- pagebreak -->\n\n'),
    images: [],
    layout: pages.map((content, index) => ({ page: index + 1, type: 'text', content })),
    metadata: {
      fileName,
      pageCount: pages.length,
      parser: 'local-word',
      pagination: 'explicit-breaks',
    },
  };
}
