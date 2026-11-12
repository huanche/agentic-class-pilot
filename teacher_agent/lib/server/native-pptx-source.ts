import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { NativePptxClick } from '@/lib/types/stage';
import { CLASSROOMS_DIR } from './classroom-storage';
import { readCourseMaterialBytes, readServerCourse } from './course-space-storage';
import { compatiblePptx, nativeClickManifest } from '@/services/onlyoffice/pptx-compat.mjs';

/** Snapshot source bytes before generation, so later material replacement cannot
 * silently change a published classroom's visuals or animation order. */
export async function prepareNativePptxSource(input: BackgroundCoursewareInput, courseId: string) {
  // Browser-submitted stage annotations never authorize access to a source file.
  delete input.stage.nativePptx;
  if (!input.preferImportedCanvas || !input.nativePptxSource) return;
  const source = input.nativePptxSource;
  const course = await readServerCourse(courseId);
  const material = course?.materials.find((m) => m.id === source.materialId);
  if (!material) throw new Error('高保真原始材料不属于当前课程');
  if (!/\.pptx$/i.test(material.name)) return;
  const bytes = await readCourseMaterialBytes(material);
  const sourceSha256 = createHash('sha256').update(bytes).digest('hex');
  if (source.sha256 !== sourceSha256) throw new Error('PPTX 来源版本已变化，请重新导入原文件');
  const prepared = await compatiblePptx(bytes);
  const manifest = await nativeClickManifest(prepared.bytes);
  const pages: Record<string, number> = {};
  const clicks: Record<string, NativePptxClick[]> = {};
  const transitions: Record<string, number> = {};
  for (const outline of input.outlines) {
    if (outline.type !== 'slide' || input.formulaEnhancedOrders?.includes(outline.order)) continue;
    const index = outline.sourceSlideOriginalIndex ?? outline.order - 1;
    if (!Number.isSafeInteger(index) || index < 0 || index >= prepared.report.pageCount)
      throw new Error('原稿页码无效');
    pages[outline.id] = index + 1;
    clicks[outline.id] = manifest[index].clicks;
    transitions[outline.id] = manifest[index].transitionMs;
  }
  if (!Object.keys(pages).length) return;
  const directory = path.join(CLASSROOMS_DIR, input.stage.id, 'native');
  await fs.mkdir(directory, { recursive: true });
  const temporary = path.join(directory, 'source.pptx.tmp');
  await fs.writeFile(temporary, prepared.bytes);
  await fs.rename(temporary, path.join(directory, 'source.pptx'));
  input.stage.nativePptx = {
    version: 1,
    renderRevision: 1,
    sourceSha256,
    sha256: createHash('sha256').update(prepared.bytes).digest('hex'),
    pages,
    clicks,
    transitions,
    compatibility: { converted: prepared.report.converted, unresolved: prepared.report.unresolved },
  };
}
