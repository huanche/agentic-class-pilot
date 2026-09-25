import { nanoid } from 'nanoid';
import { internalTeacherRequest } from '@/lib/server/platform-runtime';
import type { ParsedPdfContent } from '@/lib/types/pdf';
import type { CourseMaterialChunk, CourseMaterialExtraction } from '@/lib/course-space/types';
import {
  readCourseMaterialBytes,
  readServerCourse,
  saveMaterialExtraction,
  updateServerCourse,
} from '@/lib/server/course-space-storage';
import { extractPptxText } from '@/lib/server/pptx-text-extractor';
import { extractLegacyPptText } from '@/lib/server/ppt-text-extractor';

function replaceUnpairedSurrogates(value: string): string {
  return value.replace(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g, '\uFFFD');
}

/** PostgreSQL JSONB rejects escaped, unpaired surrogates emitted by some PDF extractors. */
export function sanitizeParsedContent(parsed: ParsedPdfContent): ParsedPdfContent {
  return {
    ...parsed,
    text: replaceUnpairedSurrogates(parsed.text),
    layout: parsed.layout?.map((item) => ({ ...item, content: replaceUnpairedSurrogates(item.content) })),
    formulas: parsed.formulas?.map((formula) => ({ ...formula, latex: replaceUnpairedSurrogates(formula.latex) })),
  };
}

export function splitIntoPageChunks(materialId: string, parsed: ParsedPdfContent): CourseMaterialChunk[] {
  const byPage = new Map<number, string[]>();
  for (const item of parsed.layout ?? []) {
    const page = Math.max(1, item.page || 1);
    if (item.content.trim()) byPage.set(page, [...(byPage.get(page) ?? []), item.content.trim()]);
  }
  for (const formula of parsed.formulas ?? []) {
    const page = Math.max(1, formula.page || 1);
    byPage.set(page, [...(byPage.get(page) ?? []), `[公式] ${formula.latex}`]);
  }
  if (byPage.size > 0) {
    return [...byPage.entries()]
      .sort(([a], [b]) => a - b)
      .map(([page, parts]) => ({ id: nanoid(12), materialId, page, text: parts.join('\n') }));
  }

  const pageCount = Math.max(1, parsed.metadata?.pageCount || 1);
  const sections = parsed.text
    .split(/\f|<!--\s*pagebreak\s*-->|\n-{3,}\n/gi)
    .map((part) => part.trim())
    .filter(Boolean);
  if (sections.length > 1) {
    return sections.map((text, index) => ({ id: nanoid(12), materialId, page: index + 1, text }));
  }
  const text = parsed.text.trim();
  const size = Math.max(1, Math.ceil(text.length / pageCount));
  return Array.from({ length: pageCount }, (_, index) => ({
    id: nanoid(12),
    materialId,
    page: index + 1,
    text: text.slice(index * size, (index + 1) * size).trim(),
  })).filter((chunk) => chunk.text);
}

export async function parseStoredCourseMaterial(input: {
  courseId: string;
  materialId: string;
  baseUrl: string;
}) {
  const course = await readServerCourse(input.courseId);
  const material = course?.materials.find((item) => item.id === input.materialId);
  if (!course || !material) throw new Error('课程材料不存在');

  await updateServerCourse(input.courseId, (current) => ({
    ...current,
    materials: current.materials.map((item) =>
      item.id === input.materialId
        ? { ...item, status: 'parsing', error: undefined, updatedAt: Date.now() }
        : item,
    ),
  }));

  try {
    const bytes = await readCourseMaterialBytes(material);
    let parsed: ParsedPdfContent;
    const lowerName = material.name.toLowerCase();
    if (lowerName.endsWith('.pptx')) {
      parsed = await extractPptxText(bytes, material.name);
    } else if (lowerName.endsWith('.ppt')) {
      parsed = await extractLegacyPptText(bytes, material.name);
    } else {
      const form = new FormData();
      form.append('file', new File([new Uint8Array(bytes)], material.name, { type: material.mimeType }));
      const internal = internalTeacherRequest(input.baseUrl, course.teacherId);
      const response = await fetch(`${internal.baseUrl}/api/extract-document`, {
        method: 'POST', body: form, headers: internal.headers, redirect: 'error',
      });
      const payload = (await response.json()) as { success: boolean; data?: ParsedPdfContent; error?: string };
      if (!response.ok || !payload.success || !payload.data) {
        throw new Error(payload.error || `材料解析失败（HTTP ${response.status}）`);
      }
      parsed = payload.data;
    }
    parsed = sanitizeParsedContent(parsed);
    const extraction: CourseMaterialExtraction = {
      materialId: material.id,
      courseId: course.id,
      sourceSha256: material.sha256 || '',
      text: parsed.text,
      pageCount: Math.max(1, parsed.metadata?.pageCount || 1),
      parser: parsed.metadata?.parser,
      chunks: splitIntoPageChunks(material.id, parsed),
      formulas: (parsed.formulas ?? []).map((formula) => ({
        page: Math.max(1, formula.page || 1),
        latex: formula.latex,
      })),
      createdAt: Date.now(),
    };
    await saveMaterialExtraction(extraction);
    await updateServerCourse(input.courseId, (current) => ({
      ...current,
      materials: current.materials.map((item) =>
        item.id === input.materialId
          ? {
              ...item,
              status: 'ready',
              pageCount: extraction.pageCount,
              parser: extraction.parser,
              extractedAt: Date.now(),
              updatedAt: Date.now(),
            }
          : item,
      ),
    }));
    return extraction;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await updateServerCourse(input.courseId, (current) => ({
      ...current,
      materials: current.materials.map((item) =>
        item.id === input.materialId
          ? { ...item, status: 'failed', error: message, updatedAt: Date.now() }
          : item,
      ),
    }));
    throw error;
  }
}
