import { toMarkdown } from '@mdgate/ppt';
import type { ParsedPdfContent } from '@/lib/types/pdf';

function splitSlides(markdown: string): string[] {
  const starts = [...markdown.matchAll(/^##\s+/gm)].map((match) => match.index ?? 0);
  if (starts.length === 0) return markdown.trim() ? [markdown.trim()] : [];
  return starts.map((start, index) => markdown.slice(start, starts[index + 1] ?? markdown.length).trim());
}

/** Parse PowerPoint 97-2003 OLE files locally; no Office, LibreOffice or cloud key required. */
export async function extractLegacyPptText(buffer: Buffer, fileName: string): Promise<ParsedPdfContent> {
  const markdown = await toMarkdown(new Uint8Array(buffer), { path: fileName });
  const slides = splitSlides(markdown);
  if (slides.length === 0) throw new Error('旧版 PPT 中未提取到可用文字');
  return {
    text: slides.map((text, index) => `<!-- slide:${index + 1} -->\n${text}`).join('\n\n<!-- pagebreak -->\n\n'),
    images: [],
    layout: slides.map((content, index) => ({ page: index + 1, type: 'text', content })),
    metadata: { pageCount: slides.length, fileName, parser: 'local-ppt-ole' },
  };
}
