import { nanoid } from 'nanoid';
import type { Slide } from '@openmaic/dsl';
import type * as MaicImport from '@openmaic/importer';
import type { GenerationSessionState } from '@/app/generation-preview/types';
import type { CourseMaterialRecord } from '@/lib/course-space';
import { fingerprintCoursewareFile } from '@/lib/course-governance/fingerprint';
import { buildFaithfulCoursewareRequirement } from '@/lib/learning-skills/courseware-mode';
import {
  buildImportedPptDraft,
  removeImportedPptSlides,
  storeImportedPptSlides,
} from './pptx-course';

/** Both workspace entry points read the original PPTX and retain its editable canvas. */
export async function prepareCourseSpacePptx(
  material: CourseMaterialRecord,
  session: GenerationSessionState,
): Promise<GenerationSessionState> {
  const response = await fetch(
    `/api/course-space/${encodeURIComponent(material.courseId)}/materials/${encodeURIComponent(material.id)}`,
    { cache: 'no-store' },
  );
  if (!response.ok) throw new Error('读取课程原始材料失败');
  const file = new File([await response.blob()], material.name, {
    type: material.mimeType,
    lastModified: material.updatedAt,
  });
  const parserUrl = '/vendor/maic-importer/index.js';
  if (!(await fetch(parserUrl, { method: 'HEAD' })).ok) throw new Error('PPTX 解析器尚未部署');
  const importer = (await import(
    /* webpackIgnore: true */
    /* turbopackIgnore: true */
    /* @vite-ignore */
    parserUrl
  )) as typeof MaicImport;
  const slides = (await importer.importPptx(file)) as Slide[];
  if (!slides.length) throw new Error('PPTX 中没有可用页面');
  const sourceFingerprint = await fingerprintCoursewareFile(file, slides.length);
  const key = `course-space-pptx-${nanoid()}`;
  try {
    await storeImportedPptSlides(key, slides, sourceFingerprint);
    return {
      ...session,
      requirements: {
        ...session.requirements,
        requirement:
          session.conversionMode === 'faithful'
            ? `${buildFaithfulCoursewareRequirement('pptx', slides.length)}\n\n${session.requirements.requirement}`
            : session.requirements.requirement,
      },
      pptContentDraft: buildImportedPptDraft(slides),
      pptxImportStorageKey: key,
      sourceFingerprint,
      previewPhase: 'ppt-review',
      courseSpaceContext: { ...session.courseSpaceContext!, materialId: material.id },
    };
  } catch (error) {
    await removeImportedPptSlides(key).catch(() => undefined);
    throw error;
  }
}
