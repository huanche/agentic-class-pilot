import JSZip from 'jszip';
import type { ParsedPdfContent } from '@/lib/types/pdf';

function decodeXml(value: string) {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&');
}

function textRuns(xml: string) {
  return [...xml.matchAll(/<a:t(?:\s[^>]*)?>([\s\S]*?)<\/a:t>/g)]
    .map((match) => decodeXml(match[1]).trim())
    .filter(Boolean);
}

export async function extractPptxText(buffer: Buffer, fileName: string): Promise<ParsedPdfContent> {
  const zip = await JSZip.loadAsync(buffer);
  const slideNames = Object.keys(zip.files)
    .filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
    .sort((a, b) => Number(a.match(/slide(\d+)/)?.[1]) - Number(b.match(/slide(\d+)/)?.[1]));
  const layout: NonNullable<ParsedPdfContent['layout']> = [];
  const pageTexts: string[] = [];
  for (const [index, name] of slideNames.entries()) {
    const xml = await zip.file(name)?.async('text');
    if (!xml) continue;
    const runs = textRuns(xml);
    const page = index + 1;
    const noteName = `ppt/notesSlides/notesSlide${page}.xml`;
    const notesXml = await zip.file(noteName)?.async('text');
    const notes = notesXml ? textRuns(notesXml).filter((text) => !/^\d+$/.test(text)) : [];
    const combined = [...runs, ...notes.map((text) => `[备注] ${text}`)];
    pageTexts.push(`## 第 ${page} 页\n${combined.join('\n')}`);
    combined.forEach((content, itemIndex) => layout.push({
      page,
      type: itemIndex === 0 ? 'title' : 'text',
      content,
    }));
  }
  if (slideNames.length === 0) throw new Error('PPTX 中未找到幻灯片页面');
  return {
    text: pageTexts.join('\n\n<!-- pagebreak -->\n\n'),
    images: [],
    layout,
    metadata: { pageCount: slideNames.length, fileName, parser: 'local-pptx-xml' },
  };
}
