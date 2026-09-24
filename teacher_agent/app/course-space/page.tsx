'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { nanoid } from 'nanoid';
import {
  ArrowLeft,
  CheckCircle2,
  GripHorizontal,
  LayoutGrid,
  LoaderCircle,
  PackageCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CoursewareModeDialog } from '@/components/generation/courseware-mode-dialog';
import { CourseWorkspaceExplorer } from '@/components/course-space/course-workspace-explorer';
import { CourseIntelligencePanel } from '@/components/course-space/course-intelligence-panel';
import { CourseArtifactGallery } from '@/components/course-space/course-artifact-gallery';
import { CourseWorkLocationPicker } from '@/components/course-space/course-work-location-picker';
import { TeacherWorkspaceAgent } from '@/components/course-space/teacher-workspace-agent';
import { postSaasHostMessage } from '@/lib/integration/host-bridge';
import { CourseCenter } from '@/components/course-space/course-center';
import type { Slide } from '@openmaic/dsl';
import type * as MaicImport from '@openmaic/importer';
import type { PptContentDraft } from '@/lib/types/generation';
import type { CoursewareConversionMode } from '@/lib/learning-skills/courseware-mode';
import { useSettingsStore } from '@/lib/store/settings';
import { useUserProfileStore } from '@/lib/store/user-profile';
import { fingerprintCoursewareFile } from '@/lib/course-governance/fingerprint';
import {
  buildFaithfulCoursewareRequirement,
  buildLearningSkillsEnhancementRequirement,
} from '@/lib/learning-skills/courseware-mode';
import {
  buildImportedPptDraft,
  removeImportedPptSlides,
  storeImportedPptSlides,
} from '@/lib/import/pptx-course';
import {
  ApiCourseSpaceRepository,
  DEFAULT_TEACHER_ID,
  type CourseArtifactJob,
  type CourseArtifactRecord,
  type CourseArtifactType,
  type CourseLesson,
  type CourseModule,
  type CourseMaterialExtraction,
  type CourseSpace,
} from '@/lib/course-space';

async function api<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { success?: boolean; error?: string };
  if (!response.ok || payload.success === false)
    throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function buildLegacyPptDraft(extraction: CourseMaterialExtraction): PptContentDraft {
  return {
    slides: extraction.chunks.map((chunk) => {
      const lines = chunk.text
        .split('\n')
        .map((line) =>
          line
            .replace(/^#+\s*/, '')
            .replace(/\*\*/g, '')
            .trim(),
        )
        .filter(Boolean);
      return {
        id: `course-material-${extraction.materialId}-${chunk.page}`,
        originalIndex: Math.max(0, chunk.page - 1),
        title: lines[0]?.slice(0, 80) || `第 ${chunk.page} 页`,
        content: lines.slice(1).join('\n'),
        speakerNotes: '',
        include: true,
        formulas: extraction.formulas
          .filter((formula) => formula.page === chunk.page)
          .map((formula) => formula.latex),
        generationStrategy: extraction.formulas.some((formula) => formula.page === chunk.page)
          ? ('ai-formula-enhanced' as const)
          : ('faithful' as const),
      };
    }),
    revision: 1,
    updatedAt: Date.now(),
  };
}

export default function CourseSpacePage() {
  const router = useRouter();
  const pathname = usePathname();
  const isTeacherV11 = pathname.startsWith('/teacher-workspace');
  const repository = useMemo(() => new ApiCourseSpaceRepository(), []);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const verticalSplitRef = useRef<HTMLDivElement>(null);
  const [courses, setCourses] = useState<CourseSpace[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [jobs, setJobs] = useState<CourseArtifactJob[]>([]);
  const [artifacts, setArtifacts] = useState<CourseArtifactRecord[]>([]);
  const [newCourseTitle, setNewCourseTitle] = useState('');
  const [newModuleTitle, setNewModuleTitle] = useState('');
  const [newLessonTitle, setNewLessonTitle] = useState('');
  const [lessonModuleId, setLessonModuleId] = useState('');
  const [generationScope, setGenerationScope] = useState('course');
  const [message, setMessage] = useState('');
  const [coursewareModeOpen, setCoursewareModeOpen] = useState(false);
  const [workspacePanel, setWorkspacePanel] = useState<'generate' | 'artifacts'>('generate');
  const [coursewareMaterialId, setCoursewareMaterialId] = useState('');
  const [launchingCourseware, setLaunchingCourseware] = useState(false);
  const [publishingCourse, setPublishingCourse] = useState(false);
  const [workspaceCourseId, setWorkspaceCourseId] = useState<string | null | undefined>();
  const [courseAreaHeight, setCourseAreaHeight] = useState(790);
  const [workbenchHeight, setWorkbenchHeight] = useState(500);
  const selected = courses.find((course) => course.id === selectedId);

  useEffect(() => {
    postSaasHostMessage('TEACHER_WORKSPACE_READY', {
      capabilities: [
        'courseware-generation',
        'knowledge-graph',
        'artifact-review',
        'classroom-player',
      ],
      courseId: selected?.id,
    });
  }, [selected?.id]);

  useEffect(() => {
    const savedTop = Number(window.localStorage.getItem('mentra.course-area-height'));
    const savedBottom = Number(window.localStorage.getItem('mentra.workbench-height'));
    if (Number.isFinite(savedTop) && savedTop >= 420 && savedTop <= 1100)
      setCourseAreaHeight(savedTop);
    if (Number.isFinite(savedBottom) && savedBottom >= 300 && savedBottom <= 850)
      setWorkbenchHeight(savedBottom);
  }, []);

  const startVerticalResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startY = event.clientY;
    const startTop = courseAreaHeight;
    const startBottom = workbenchHeight;
    const move = (pointerEvent: PointerEvent) => {
      const delta = pointerEvent.clientY - startY;
      const limited = Math.min(1100 - startTop, startBottom - 300, Math.max(420 - startTop, delta));
      setCourseAreaHeight(Math.round(startTop + limited));
      setWorkbenchHeight(Math.round(startBottom - limited));
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      setCourseAreaHeight((value) => {
        window.localStorage.setItem('mentra.course-area-height', String(value));
        return value;
      });
      setWorkbenchHeight((value) => {
        window.localStorage.setItem('mentra.workbench-height', String(value));
        return value;
      });
    };
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
    window.addEventListener('pointercancel', stop, { once: true });
  };

  const refresh = useCallback(
    async (preferredId?: string) => {
      const items = await repository.listByTeacher(DEFAULT_TEACHER_ID);
      const id = preferredId ?? selectedId ?? items[0]?.id;
      setCourses(items);
      setSelectedId(id);
      if (id) {
        const detail = await api<{
          course: CourseSpace;
          jobs: CourseArtifactJob[];
          artifacts: CourseArtifactRecord[];
        }>(await fetch(`/api/course-space/${id}`, { cache: 'no-store' }));
        setCourses((current) => current.map((item) => (item.id === id ? detail.course : item)));
        setJobs(detail.jobs);
        setArtifacts(detail.artifacts);
      }
    },
    [repository, selectedId],
  );

  useEffect(() => {
    const requestedCourseId = new URLSearchParams(window.location.search).get('workspace');
    setWorkspaceCourseId(requestedCourseId);
    if (!requestedCourseId) return;
    const timer = window.setTimeout(() => void refresh(requestedCourseId), 0);
    return () => window.clearTimeout(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const active =
      selected?.materials.some((item) => item.status === 'parsing') ||
      jobs.some((job) => ['queued', 'running'].includes(job.status));
    if (!selected || !active) return;
    const timer = window.setInterval(() => void refresh(selected.id), 2500);
    return () => window.clearInterval(timer);
  }, [jobs, refresh, selected]);

  const createCourse = async () => {
    if (!newCourseTitle.trim()) return;
    const course = await repository.create({
      teacherId: DEFAULT_TEACHER_ID,
      title: newCourseTitle,
    });
    setNewCourseTitle('');
    setWorkspaceCourseId(course.id);
    window.history.replaceState(null, '', `/course-space?workspace=${course.id}`);
    await refresh(course.id);
  };

  const saveStructure = async (course: CourseSpace) => {
    await repository.save(course);
    await refresh(course.id);
  };

  const publishCourse = async () => {
    if (!selected || publishingCourse) return;
    setPublishingCourse(true);
    setMessage('');
    try {
      await api(await fetch(`/api/course-space/${selected.id}/publish`, { method: 'POST' }));
      await refresh(selected.id);
      setMessage('课程已发布到授课班级通道。教师激活的资料将在班级详情中显示。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setPublishingCourse(false);
    }
  };

  const addModule = async () => {
    if (!selected || !newModuleTitle.trim()) return;
    const now = Date.now();
    const courseModule: CourseModule = {
      id: nanoid(10),
      courseId: selected.id,
      title: newModuleTitle.trim(),
      order: selected.modules.length + 1,
      objectives: [],
      lessons: [],
      createdAt: now,
      updatedAt: now,
    };
    setNewModuleTitle('');
    await saveStructure({
      ...selected,
      modules: [...selected.modules, courseModule],
      updatedAt: now,
    });
  };

  const addLesson = async () => {
    if (!selected || !lessonModuleId || !newLessonTitle.trim()) return;
    const now = Date.now();
    const target = selected.modules.find((item) => item.id === lessonModuleId);
    if (!target) return;
    const lesson: CourseLesson = {
      id: nanoid(10),
      moduleId: target.id,
      title: newLessonTitle.trim(),
      order: target.lessons.length + 1,
      objectives: [],
      materialIds: [],
      createdAt: now,
      updatedAt: now,
    };
    setNewLessonTitle('');
    await saveStructure({
      ...selected,
      modules: selected.modules.map((item) =>
        item.id === target.id
          ? { ...item, lessons: [...item.lessons, lesson], updatedAt: now }
          : item,
      ),
      updatedAt: now,
    });
  };

  const uploadMaterials = async (files: File[]) => {
    if (!selected) return;
    try {
      for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        await api(
          await fetch(`/api/course-space/${selected.id}/materials`, { method: 'POST', body: form }),
        );
      }
      setMessage('材料已保存到课程空间。不会自动解析或生成，请由教师继续操作。');
      await refresh(selected.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const parseMaterial = async (materialId: string) => {
    if (!selected) return;
    try {
      await api(
        await fetch(`/api/course-space/${selected.id}/materials/${materialId}/parse`, {
          method: 'POST',
        }),
      );
      setMessage('材料解析任务已启动，页码、公式和来源指纹将写入课程知识底座。');
      await refresh(selected.id);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const resolveGenerationScope = (): CourseArtifactJob['scope'] => {
    if (generationScope.startsWith('module:')) {
      const moduleId = generationScope.slice(7);
      if (selected?.modules.some((item) => item.id === moduleId))
        return { type: 'module', moduleId };
    }
    if (generationScope.startsWith('lesson:')) {
      const lessonId = generationScope.slice(7);
      if (selected?.modules.some((item) => item.lessons.some((lesson) => lesson.id === lessonId)))
        return { type: 'lesson', lessonId };
    }
    return { type: 'course' };
  };
  const updateGenerationScope = (scope: CourseArtifactJob['scope']) =>
    setGenerationScope(
      scope.type === 'course'
        ? 'course'
        : scope.type === 'module'
          ? `module:${scope.moduleId}`
          : `lesson:${scope.lessonId}`,
    );

  const coursewareMaterials =
    selected?.materials.filter((item) => item.status === 'ready' && /\.pptx?$/i.test(item.name)) ??
    [];
  const selectedCoursewareMaterial =
    coursewareMaterials.find((item) => item.id === coursewareMaterialId) ?? coursewareMaterials[0];
  const latestJob = [...jobs].sort((a, b) => b.createdAt - a.createdAt)[0];
  const activeScope = resolveGenerationScope();
  const activeScopeKey =
    activeScope.type === 'course'
      ? 'course'
      : activeScope.type === 'module'
        ? `module:${activeScope.moduleId}`
        : `lesson:${activeScope.lessonId}`;

  const scopeTitle = () => {
    if (!selected) return '课程课件';
    const scope = resolveGenerationScope();
    if (scope.type === 'course') return selected.title;
    if (scope.type === 'module')
      return selected.modules.find((item) => item.id === scope.moduleId)?.title || selected.title;
    for (const courseModule of selected.modules) {
      const lesson = courseModule.lessons.find((item) => item.id === scope.lessonId);
      if (lesson) return `${courseModule.title} / ${lesson.title}`;
    }
    return selected.title;
  };
  const workbenchLocation = selected
    ? activeScope.type === 'course'
      ? selected.title
      : `${selected.title} / ${scopeTitle()}`
    : '';

  useEffect(() => {
    if (!selected) return;
    const scope = activeScopeKey.startsWith('module:')
      ? { type: 'module' as const, moduleId: activeScopeKey.slice(7) }
      : activeScopeKey.startsWith('lesson:')
        ? { type: 'lesson' as const, lessonId: activeScopeKey.slice(7) }
        : { type: 'course' as const };
    postSaasHostMessage('WORK_SCOPE_CHANGED', {
      courseId: selected.id,
      scope,
      displayPath: workbenchLocation,
    });
  }, [selected, activeScopeKey, workbenchLocation]);

  const launchCoursewareFlow = async (mode: CoursewareConversionMode) => {
    if (!selected || !selectedCoursewareMaterial) return;
    if (mode === 'faithful' && !selectedCoursewareMaterial.name.toLowerCase().endsWith('.pptx')) {
      setMessage('旧版 .ppt 无法保留可编辑视觉画布，请上传 .pptx，或选择 AI 增强课件。');
      return;
    }
    setCoursewareModeOpen(false);
    setLaunchingCourseware(true);
    let importStorageKey: string | undefined;
    try {
      const materialResponse = await fetch(
        `/api/course-space/${selected.id}/materials/${selectedCoursewareMaterial.id}`,
        { cache: 'no-store' },
      );
      if (!materialResponse.ok) throw new Error('读取课程原始材料失败');
      const file = new File([await materialResponse.blob()], selectedCoursewareMaterial.name, {
        type: selectedCoursewareMaterial.mimeType,
        lastModified: selectedCoursewareMaterial.updatedAt,
      });
      let draft: PptContentDraft;
      let sourceFingerprint;
      if (file.name.toLowerCase().endsWith('.pptx')) {
        const parserUrl = '/vendor/maic-importer/index.js';
        const parserProbe = await fetch(parserUrl, { method: 'HEAD' });
        if (!parserProbe.ok) throw new Error('PPTX 解析器尚未部署');
        const importer = (await import(
          /* webpackIgnore: true */
          /* turbopackIgnore: true */
          /* @vite-ignore */
          parserUrl
        )) as typeof MaicImport;
        const slides = (await importer.importPptx(file)) as Slide[];
        if (slides.length === 0) throw new Error('PPTX 中没有可用页面');
        sourceFingerprint = await fingerprintCoursewareFile(file, slides.length);
        draft = buildImportedPptDraft(slides);
        // Match the quick-generation workflow: retain the visual canvas for
        // both routes. AI enhancement still redraws when the model succeeds;
        // this canvas prevents a text-only degradation when it does not.
        importStorageKey = `course-space-pptx-${nanoid()}`;
        await storeImportedPptSlides(importStorageKey, slides, sourceFingerprint);
      } else {
        const extraction = (
          await api<{ extraction: CourseMaterialExtraction }>(
            await fetch(
              `/api/course-space/${selected.id}/materials/${selectedCoursewareMaterial.id}/extraction`,
              { cache: 'no-store' },
            ),
          )
        ).extraction;
        draft = buildLegacyPptDraft(extraction);
        sourceFingerprint = {
          algorithm: 'SHA-256' as const,
          sha256: selectedCoursewareMaterial.sha256 || extraction.sourceSha256,
          fileName: selectedCoursewareMaterial.name,
          mimeType: selectedCoursewareMaterial.mimeType,
          byteLength: selectedCoursewareMaterial.size,
          lastModified: selectedCoursewareMaterial.updatedAt,
          pageCount: extraction.pageCount,
          importedAt: Date.now(),
        };
      }

      const settings = useSettingsStore.getState();
      settings.setTTSEnabled(true);
      settings.setTTSProvider('qwen-tts');
      const profile = useUserProfileStore.getState();
      const target = scopeTitle();
      const requirement =
        mode === 'faithful'
          ? `${buildFaithfulCoursewareRequirement('pptx', draft.slides.length)}\n\n课程空间范围：${target}`
          : buildLearningSkillsEnhancementRequirement(
              `围绕“${target}”生成课时 PPT 或互动课件。`,
              'pptx',
            );
      sessionStorage.setItem(
        'generationSession',
        JSON.stringify({
          sessionId: nanoid(),
          requirements: {
            requirement,
            userNickname: profile.nickname || undefined,
            userBio: profile.bio || undefined,
            webSearch: false,
            interactiveMode: false,
          },
          pdfText: '',
          pdfImages: [],
          imageStorageIds: [],
          sceneOutlines: undefined,
          pptContentDraft: draft,
          currentStep: 'generating',
          previewPhase: 'ppt-review',
          sourceType: mode === 'faithful' ? 'pptx-faithful' : 'learning-skills-enhanced',
          conversionMode: mode,
          pptxImportStorageKey: importStorageKey,
          sourceFingerprint,
          courseSpaceContext: {
            courseId: selected.id,
            materialId: selectedCoursewareMaterial.id,
            scope: resolveGenerationScope(),
          },
        }),
      );
      router.push('/generation-preview');
    } catch (error) {
      await removeImportedPptSlides(importStorageKey).catch(() => undefined);
      setMessage(error instanceof Error ? error.message : String(error));
      setLaunchingCourseware(false);
    }
  };

  const requestGeneration = async (
    requestedType: CourseArtifactType,
    requestedScope?: CourseArtifactJob['scope'],
  ) => {
    const artifactTypes = [requestedType];
    if (!selected) return;
    const scope = requestedScope ?? resolveGenerationScope();
    if (requestedScope)
      setGenerationScope(
        requestedScope.type === 'course'
          ? 'course'
          : requestedScope.type === 'module'
            ? `module:${requestedScope.moduleId}`
            : `lesson:${requestedScope.lessonId}`,
      );
    const includesCourseware = artifactTypes.includes('lesson-courseware');
    // A supplied PPT/PPTX takes the reviewable conversion path. For every
    // other parsed material, create a normal AI courseware job instead. The
    // previous implementation rejected TXT/PDF/Word materials here even
    // though the server-side courseware generator supports their extraction.
    const convertExistingPpt = includesCourseware && Boolean(selectedCoursewareMaterial);
    const backgroundArtifacts = convertExistingPpt
      ? artifactTypes.filter((type) => type !== 'lesson-courseware')
      : artifactTypes;
    try {
      let jobCount = 0;
      let createdJob: CourseArtifactJob | undefined;
      if (backgroundArtifacts.length > 0) {
        const result = await api<{ jobs: CourseArtifactJob[] }>(
          await fetch(`/api/course-space/${selected.id}/jobs`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ scope, artifactTypes: backgroundArtifacts }),
          }),
        );
        jobCount = result.jobs.length;
        createdJob = result.jobs[0];
        await refresh(selected.id);
      }
      if (convertExistingPpt && selectedCoursewareMaterial) {
        setCoursewareMaterialId(selectedCoursewareMaterial.id);
        setCoursewareModeOpen(true);
        setMessage(
          jobCount
            ? `已创建 ${jobCount} 个资料类任务；请继续选择课件转换路径。`
            : '请选择高保真还原或 AI 增强课件。',
        );
      } else {
        setMessage(includesCourseware
          ? '已创建 AI 互动课件生成任务。生成结果须经教师审核、激活后才能用于授课。'
          : `已创建 ${jobCount} 个后台任务。生成结果必须经过教师审核后才能发布。`);
        if (createdJob) router.push(`/course-space/${selected.id}/jobs/${createdJob.id}`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  if (workspaceCourseId === undefined)
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 text-muted-foreground">
        正在打开课程中心…
      </main>
    );
  if (workspaceCourseId === null) return <CourseCenter />;

  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_28%_8%,rgba(59,130,246,0.10),transparent_28%),radial-gradient(circle_at_72%_88%,rgba(176,0,85,0.08),transparent_30%),linear-gradient(to_bottom,#f8fafc,#f3f6fa)] text-slate-900">
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-white/70 bg-white/75 px-6 py-3 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="rounded-full"
            onClick={() => router.push(`/course-space/${selected?.id || workspaceCourseId}`)}
          >
            <ArrowLeft />
          </Button>
          <img src="/mentra-icon.svg" alt="MENTRA" className="size-9" />
          <div className="h-7 w-px bg-slate-200" />
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold">教师课程工作区</h1>
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${isTeacherV11 ? 'border-[#B00055]/20 bg-[#B00055]/5 text-[#B00055]' : 'border-slate-200 bg-slate-50 text-slate-500'}`}
              >
                教师端 {isTeacherV11 ? 'v1.1' : 'v1.0'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">课程结构、智能体协作与历史教学产物</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            className="rounded-full bg-white/70"
            onClick={() => router.push('/')}
          >
            返回品牌首页
          </Button>
          <div className="rounded-full border bg-white/70 px-3 py-1.5 text-xs text-muted-foreground">
            默认教师
          </div>
        </div>
      </header>
      <div className="p-4">
        {selected && (
          <div className="mx-auto max-w-[1760px] space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3 px-1">
              <div>
                <h2 className="text-xl font-semibold">{selected.title}</h2>
                <p className="text-xs text-muted-foreground">
                  按课程—模块—课时浏览课件、知识点与教学文件
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="rounded-full border bg-white px-3 py-1.5">
                  {selected.modules.length} 模块
                </span>
                <span className="rounded-full border bg-white px-3 py-1.5">
                  {artifacts.length} 产物
                </span>
                {latestJob && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/course-space/${selected.id}/jobs/${latestJob.id}`)}
                  >
                    最近任务
                  </Button>
                )}
                <Button
                  size="sm"
                  className="bg-[#B00055] hover:bg-[#8F0046]"
                  disabled={publishingCourse || selected.status === 'active'}
                  onClick={() => void publishCourse()}
                >
                  {publishingCourse ? (
                    <LoaderCircle className="mr-2 size-4 animate-spin" />
                  ) : selected.status === 'active' ? (
                    <CheckCircle2 className="mr-2 size-4" />
                  ) : (
                    <PackageCheck className="mr-2 size-4" />
                  )}
                  {selected.status === 'active' ? 'Class 通道已开启' : '开启 Class 通道'}
                </Button>
                {selected.status === 'active' && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/classes/${selected.id}`)}
                  >
                    查看授课班级
                  </Button>
                )}
              </div>
            </div>
            <CourseIntelligencePanel course={selected} artifacts={artifacts} graphOnly />
            <CourseWorkspaceExplorer
              course={selected}
              artifacts={artifacts}
              height={courseAreaHeight}
              showOriginBadges
              onGenerate={(type, scope) => void requestGeneration(type, scope)}
              onCourseChange={saveStructure}
              onRefresh={() => refresh(selected.id)}
              onScopeChange={updateGenerationScope}
            />
            <div
              ref={verticalSplitRef}
              role="separator"
              aria-label="调整课件区与教师工作台高度"
              aria-orientation="horizontal"
              aria-valuemin={420}
              aria-valuemax={1100}
              aria-valuenow={courseAreaHeight}
              tabIndex={0}
              onPointerDown={startVerticalResize}
              onKeyDown={(event) => {
                if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
                event.preventDefault();
                const delta = event.key === 'ArrowDown' ? 20 : -20;
                const limited = Math.min(
                  1100 - courseAreaHeight,
                  workbenchHeight - 300,
                  Math.max(420 - courseAreaHeight, delta),
                );
                const nextTop = courseAreaHeight + limited;
                const nextBottom = workbenchHeight - limited;
                setCourseAreaHeight(nextTop);
                setWorkbenchHeight(nextBottom);
                window.localStorage.setItem('mentra.course-area-height', String(nextTop));
                window.localStorage.setItem('mentra.workbench-height', String(nextBottom));
              }}
              className="group relative -my-2 flex h-7 cursor-row-resize touch-none items-center justify-center outline-none"
            >
              <div className="h-1 w-24 rounded-full bg-slate-300 transition group-hover:bg-[#B00055] group-focus:bg-[#B00055]" />
              <GripHorizontal className="absolute size-4 text-slate-400 opacity-0 transition group-hover:opacity-100 group-focus:opacity-100" />
            </div>
            <section className="overflow-visible rounded-[26px] border border-white/80 bg-white/75 shadow-sm backdrop-blur-xl">
              <div className="flex items-center justify-between gap-3 border-b bg-white/85 px-4 py-3">
                <div
                  className="inline-flex rounded-xl bg-slate-100 p-1"
                  role="tablist"
                  aria-label="教师工作区视图"
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={workspacePanel === 'generate'}
                    onClick={() => setWorkspacePanel('generate')}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition ${workspacePanel === 'generate' ? 'bg-white text-[#B00055] shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
                  >
                    <LayoutGrid className="size-4" />
                    教师工作台
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={workspacePanel === 'artifacts'}
                    onClick={() => setWorkspacePanel('artifacts')}
                    className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition ${workspacePanel === 'artifacts' ? 'bg-white text-[#B00055] shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
                  >
                    <LayoutGrid className="size-4" />
                    历史产物缩略图
                  </button>
                </div>
                {workspacePanel === 'generate' ? (
                  <CourseWorkLocationPicker
                    course={selected}
                    scope={activeScope}
                    onChange={updateGenerationScope}
                  />
                ) : (
                  <p className="text-xs text-muted-foreground">
                    当前课程共 {artifacts.length} 个教学产物
                  </p>
                )}
              </div>
              <div className="p-3">
                {workspacePanel === 'generate' ? (
                  <div style={{ height: workbenchHeight }}>
                    <TeacherWorkspaceAgent
                      course={selected}
                      activeScope={activeScope}
                      embedded
                      onGenerate={(type, scope) => void requestGeneration(type, scope)}
                      onOperationComplete={() => refresh(selected.id)}
                      onOpenKnowledgeGraph={() =>
                        router.push(
                          `/course-space/${encodeURIComponent(selected.id)}/knowledge-graph/manage`,
                        )
                      }
                    />
                  </div>
                ) : (
                  <CourseArtifactGallery courseId={selected.id} artifacts={artifacts} embedded />
                )}
              </div>
            </section>
            {message && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
                {message}
              </div>
            )}
          </div>
        )}
      </div>
      <CoursewareModeDialog
        open={coursewareModeOpen}
        onOpenChange={setCoursewareModeOpen}
        onSelect={(mode) => void launchCoursewareFlow(mode)}
        sourceLabel="PPT / PPTX"
        faithfulDisabledReason={
          selectedCoursewareMaterial?.name.toLowerCase().endsWith('.ppt')
            ? '旧版 .ppt 不包含可直接复用的 OOXML 视觉画布；请上传 .pptx，或选择 AI 增强。'
            : undefined
        }
      />
    </main>
  );
}
