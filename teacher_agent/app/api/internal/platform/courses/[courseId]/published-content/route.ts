import { type NextRequest, NextResponse } from 'next/server';
import { readClassroom } from '@/lib/server/classroom-storage';
import {
  readPublishedKnowledgePackage,
  readServerCourse,
  listStoredCourseArtifacts,
} from '@/lib/server/course-space-storage';
import type {
  CourseArtifactRecord,
  CourseLesson,
  CourseLessonFile,
  CourseMaterialRecord,
  CoursePublicationPlacement,
  CourseSpace,
} from '@/lib/course-space/types';

export const dynamic = 'force-dynamic';

/**
 * One-shot read-only snapshot of everything the platform needs to assemble a
 * student learning context for a published course. This endpoint mirrors the
 * platform's legacy cross-schema queries (student_bridge._published_package_payload,
 * published_course_entries, _published_lessons, _classroom_view) with identical
 * filtering, ordering and error semantics so shadow comparisons stay meaningful.
 * The platform remains responsible for enrollment, playback grants and the
 * player URL; this route never exposes draft content.
 */

type LooseRecord = Record<string, unknown>;

function visible(item: { classVisible?: boolean; classPublicationId?: string }): boolean {
  return item.classVisible === true && !!item.classPublicationId;
}

function lessonScope(placement: CoursePublicationPlacement | undefined, fallback: unknown): unknown {
  return placement?.lessonId
    ? { type: 'lesson', lessonId: placement.lessonId }
    : fallback;
}

/** Mirror Python's html.unescape for the entities that occur in authored slides. */
const NAMED_ENTITIES: Record<string, string> = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  copy: '©', reg: '®', trade: '™', hellip: '…',
  mdash: '—', ndash: '–', lsquo: '‘', rsquo: '’',
  ldquo: '“', rdquo: '”', laquo: '«', raquo: '»',
  times: '×', divide: '÷', plusmn: '±', deg: '°',
  middot: '·', bull: '•', dagger: '†', permil: '‰',
  larr: '←', uarr: '↑', rarr: '→', darr: '↓', harr: '↔',
  minus: '−', frac12: '½', frac14: '¼', frac34: '¾',
  sup2: '²', sup3: '³', micro: 'µ', para: '¶', sect: '§',
};

function unescapeHtml(value: string): string {
  return value.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, (match, body: string) => {
    if (body.startsWith('#x') || body.startsWith('#X')) {
      const code = Number.parseInt(body.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (body.startsWith('#')) {
      const code = Number.parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return NAMED_ENTITIES[body] ?? match;
  });
}

function visibleTextOf(scene: LooseRecord): string[] {
  const content = scene.content;
  const canvas = (content && typeof content === 'object' && !Array.isArray(content)
    ? (content as LooseRecord).canvas : undefined) as LooseRecord | undefined;
  const texts: string[] = [];
  for (const element of ((canvas?.elements as unknown[] | undefined) ?? [])) {
    if (element && typeof element === 'object' && !Array.isArray(element) &&
        (element as LooseRecord).type === 'text') {
      const raw = String((element as LooseRecord).content ?? '');
      const value = unescapeHtml(raw.replace(/<[^>]*>/g, ' ')).trim();
      if (value) texts.push(value);
    }
  }
  return texts;
}

type ClassroomPayload = {
  id: string;
  stage?: unknown;
  scenes?: LooseRecord[];
};

/** Port of student_bridge._classroom_view (minus the platform-owned playerUrl). */
function classroomView(classroom: ClassroomPayload): LooseRecord {
  const stage = classroom.stage;
  const title = stage && typeof stage === 'object' && !Array.isArray(stage)
    ? String((stage as LooseRecord).name ?? '')
    : '';
  const scenes = ((classroom.scenes ?? []) as LooseRecord[]).map((scene) => ({
    id: scene.id,
    type: (scene.type as string | undefined) ?? 'slide',
    order: Math.trunc(Number(scene.order) || 1),
    title: (scene.title as string | undefined) ?? '',
    visibleText: visibleTextOf(scene),
    actions: ((scene.actions ?? []) as unknown[])
      .filter((action): action is LooseRecord =>
        !!action && typeof action === 'object' && !Array.isArray(action))
      .map((action) => ({
        id: action.id,
        type: (action.type as string | undefined) ?? 'speech',
        text: action.text,
      })),
  }));
  scenes.sort((a, b) => a.order - b.order);
  return { id: classroom.id, title, scenes };
}

function artifactEntry(artifact: CourseArtifactRecord): LooseRecord {
  const placement = artifact.publicationPlacement;
  return {
    id: artifact.id,
    title: artifact.title ?? '',
    content: artifact.content ?? '',
    citations: artifact.citations ?? [],
    scope: lessonScope(placement, artifact.scope),
    kind: 'artifact',
    resourceType: placement?.resourceType ??
      (artifact as unknown as LooseRecord).resourceType,
    publicationId: artifact.classPublicationId,
  };
}

function lessonFileEntry(lesson: CourseLesson, file: CourseLessonFile): LooseRecord {
  return {
    id: file.id,
    title: file.title ?? '',
    content: file.content ?? '',
    kind: 'lesson-file',
    resourceType: file.publicationPlacement?.resourceType ?? file.type,
    scope: { type: 'lesson', lessonId: lesson.id },
    publicationId: file.classPublicationId,
  };
}

function materialEntry(course: CourseSpace, item: CourseMaterialRecord): LooseRecord {
  return {
    id: item.id,
    title: item.name ?? '',
    content: '',
    kind: 'material',
    publicationId: item.classPublicationId,
    scope: { type: 'lesson', lessonId: item.publicationPlacement?.lessonId },
    // Path only: the platform prefixes its own TEACHER_PUBLIC_URL.
    url: `/api/course-space/${course.id}/materials/${item.id}`,
  };
}

function publishedPublishedAt(artifact: CourseArtifactRecord): number | null {
  return artifact.classPublishedAt ?? null;
}

function compareNewestFirst(a: CourseArtifactRecord, b: CourseArtifactRecord): number {
  const pa = publishedPublishedAt(a);
  const pb = publishedPublishedAt(b);
  if (pa !== null && pb !== null && pa !== pb) return pb - pa;
  if (pa === null && pb !== null) return 1;
  if (pa !== null && pb === null) return -1;
  if (a.createdAt !== b.createdAt) return b.createdAt - a.createdAt;
  return a.id < b.id ? 1 : a.id > b.id ? -1 : 0;
}

function compareOldestFirst(a: CourseArtifactRecord, b: CourseArtifactRecord): number {
  if (a.createdAt !== b.createdAt) return a.createdAt - b.createdAt;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  // The middleware strips caller-supplied delegation headers and only restores
  // this one after the platform validates the service key and subject.
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') {
    return NextResponse.json({ published: false, content: null });
  }
  const knowledgePackage = await readPublishedKnowledgePackage(course.id);
  if (!knowledgePackage || knowledgePackage.status !== 'published') {
    return NextResponse.json({ published: false, content: null });
  }

  const publishedArtifacts = (await listStoredCourseArtifacts(course.id))
    .filter((artifact) => artifact.status === 'published' &&
      artifact.classVisible === true && artifact.classPublicationId != null);

  // Entries: published artifacts first (created_at, id ASC), then lesson files
  // in course payload order, then materials.
  const entries: LooseRecord[] = publishedArtifacts
    .slice()
    .sort(compareOldestFirst)
    .map(artifactEntry);
  for (const module of course.modules ?? []) {
    for (const lesson of module.lessons ?? []) {
      for (const file of lesson.files ?? []) {
        if (visible(file)) entries.push(lessonFileEntry(lesson, file));
      }
    }
  }
  for (const item of course.materials ?? []) {
    if (visible(item)) entries.push(materialEntry(course, item));
  }

  // Lessons: one classroom per lesson, newest publication wins.
  const teacherLessons = new Map<string, CourseLesson>();
  for (const module of course.modules ?? []) {
    for (const lesson of module.lessons ?? []) teacherLessons.set(lesson.id, lesson);
  }
  const selected = new Map<string, LooseRecord>();
  for (const artifact of publishedArtifacts
      .filter((artifact) => !!artifact.classroomId)
      .sort(compareNewestFirst)) {
    const placement = artifact.publicationPlacement;
    const scope = (artifact.scope ?? {}) as LooseRecord;
    const lessonId = placement?.lessonId ??
      (scope.type === 'lesson' ? (scope.lessonId as string | undefined) : undefined);
    if (!lessonId || !teacherLessons.has(lessonId) || selected.has(lessonId)) continue;
    const lesson = teacherLessons.get(lessonId)!;
    const classroom = await readClassroom(artifact.classroomId!);
    if (!classroom) {
      // Same failure the platform raises today for a missing snapshot.
      return NextResponse.json(
        { error: '课堂不存在或尚未发布' }, { status: 404 });
    }
    selected.set(lessonId, {
      id: lessonId,
      title: artifact.title || lesson.title,
      order: lesson.order ?? 1,
      week: placement?.week ?? lesson.week,
      lessonNumber: placement?.lessonNumber ?? lesson.lessonNumber,
      teachingHours: placement?.teachingHours ?? lesson.teachingHours,
      publishedAt: artifact.classPublishedAt,
      classroom: classroomView(classroom as unknown as ClassroomPayload),
    });
  }
  const lessons = [...selected.values()].sort((a, b) => {
    // Python `or` semantics: 0 counts as unset, matching the legacy comparator.
    const weekA = (a.week as number | undefined) || 1000;
    const weekB = (b.week as number | undefined) || 1000;
    if (weekA !== weekB) return weekA - weekB;
    const numberA = (a.lessonNumber as number | undefined) || (a.order as number);
    const numberB = (b.lessonNumber as number | undefined) || (b.order as number);
    if (numberA !== numberB) return numberA - numberB;
    return String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0;
  });

  return NextResponse.json({
    published: true,
    content: {
      publication: {
        publicationId: knowledgePackage.id,
        version: knowledgePackage.version,
      },
      course: { id: course.id },
      entries,
      lessons,
    },
  });
}
