'use client';

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  Plus,
  Pin,
  Presentation,
  Sparkles,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ResourcePublicationDialog, type PublicationTarget } from './resource-publication-dialog';
import { ResourceActions } from './resource-actions';
import { SourceFileEditor } from './source-file-editor';
import { courseWorkspaceUrl, withTeacherReturn } from '@/lib/course-space/navigation';
import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseArtifactType,
  CourseLessonFile,
  CourseMaterialRecord,
  CourseSpace,
} from '@/lib/course-space';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import { markdownToArtifactHtml } from '@/lib/course-space/artifact-formats';
import { nanoid } from 'nanoid';

type Scope =
  | { type: 'course' }
  | { type: 'module'; moduleId: string }
  | { type: 'lesson'; lessonId: string };
type BrowserFile = {
  id: string;
  title: string;
  kind: 'artifact' | 'material';
  artifact?: CourseArtifactRecord;
  courseFile?: CourseLessonFile;
  material?: CourseMaterialRecord;
  scope: Scope;
};
type DragItem = { kind: 'material' | 'course-file' | 'artifact'; id: string };
const artifactPriority = (artifact: CourseArtifactRecord) =>
  artifact.type === 'lesson-courseware'
    ? 3
    : artifact.classroomUrl
      ? 2
      : artifact.type === 'course-outline'
        ? 1
        : 0;

function belongsToScope(artifact: CourseArtifactRecord, scope: Scope, course: CourseSpace) {
  if (scope.type === 'course') return artifact.scope.type === 'course';
  if (scope.type === 'module')
    return artifact.scope.type === 'module' && artifact.scope.moduleId === scope.moduleId;
  if (artifact.scope.type === 'lesson') return artifact.scope.lessonId === scope.lessonId;
  const courseModule = course.modules.find((item) =>
    item.lessons.some((lesson) => lesson.id === scope.lessonId),
  );
  return artifact.scope.type === 'module' && artifact.scope.moduleId === courseModule?.id;
}

function OriginBadge({
  origin,
  className = '',
}: {
  origin: 'teacher' | 'agent';
  className?: string;
}) {
  const isTeacher = origin === 'teacher';
  const Icon = isTeacher ? Upload : Sparkles;

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[9px] font-medium leading-none ${
        isTeacher
          ? 'border-blue-200 bg-blue-50 text-blue-700'
          : 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700'
      } ${className}`}
      title={isTeacher ? '教师上传的原始材料' : 'AI / 智能体生成的教学产物'}
    >
      <Icon className="size-2.5" />
      {isTeacher ? '教师上传' : 'AI生成'}
    </span>
  );
}

function ClassPublicationBadge({
  publicationId,
  onPublish,
}: {
  publicationId?: string;
  onPublish?: () => void;
}) {
  const published = Boolean(publicationId);
  return (
    <span
      role={!published && onPublish ? 'button' : undefined}
      tabIndex={!published && onPublish ? 0 : undefined}
      onClick={(event) => {
        if (published || !onPublish) return;
        event.preventDefault();
        event.stopPropagation();
        onPublish();
      }}
      onKeyDown={(event) => {
        if (published || !onPublish || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        event.stopPropagation();
        onPublish();
      }}
      className={`inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9px] font-medium leading-none ${
        published
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
          : onPublish
            ? 'cursor-pointer border-[#B00055]/25 bg-white text-[#B00055] hover:bg-[#B00055] hover:text-white'
            : 'border-slate-200 bg-slate-50 text-slate-500'
      }`}
      title={
        published ? `已发布到 Class 通道 · 唯一标志 ${publicationId}` : '尚未发布到 Class 通道'
      }
    >
      {published ? `已发布·${publicationId!.slice(-6)}` : '未发布'}
    </span>
  );
}

export function CourseWorkspaceExplorer({
  course,
  artifacts,
  onGenerate: _onGenerate,
  onCourseChange,
  onRefresh,
  onScopeChange,
  showOriginBadges = false,
  height = 790,
  focusRequest,
}: {
  course: CourseSpace;
  artifacts: CourseArtifactRecord[];
  onGenerate: (type: CourseArtifactType, scope?: CourseArtifactJob['scope']) => void;
  onCourseChange: (course: CourseSpace) => Promise<void>;
  onRefresh: () => Promise<void>;
  onScopeChange?: (scope: CourseArtifactJob['scope']) => void;
  showOriginBadges?: boolean;
  height?: number;
  focusRequest?: {
    nonce: number;
    folder: 'materials' | 'outline' | 'courseware';
    fileId?: string;
    lessonId?: string;
  };
}) {
  const firstLesson = course.modules.flatMap((item) => item.lessons)[0];
  const initialArtifact = [...artifacts].sort(
    (a, b) => artifactPriority(b) - artifactPriority(a) || b.updatedAt - a.updatedAt,
  )[0];
  const [scope, setScope] = useState<Scope>(
    initialArtifact?.scope ??
      (firstLesson ? { type: 'lesson', lessonId: firstLesson.id } : { type: 'course' }),
  );
  const [expanded, setExpanded] = useState(
    () =>
      new Set(
        course.modules
          .filter((item) => item.workspaceKind !== 'week' || item.week === 1)
          .map((item) => item.id),
      ),
  );
  const [expandedLessons, setExpandedLessons] = useState(() => new Set<string>());
  const [courseFilesExpanded, setCourseFilesExpanded] = useState(true);
  const [folderView, setFolderView] = useState('AI课件');
  const [openTemplates, setOpenTemplates] = useState(new Set(['课程资料', '课程大纲']));
  const [selectedFileId, setSelectedFileId] = useState('');
  const [savingStructure, setSavingStructure] = useState(false);
  const [treeMessage, setTreeMessage] = useState('');
  const [editingFileId, setEditingFileId] = useState('');
  const [revealRequest, setRevealRequest] = useState<{
    id: string;
    nonce: number;
    lessonId?: string;
  }>();
  const [sourceEditId, setSourceEditId] = useState('');
  const [newFolder, setNewFolder] = useState<{
    kind: 'module' | 'lesson' | 'courseware';
    moduleId?: string;
  }>();
  const [newFolderTitle, setNewFolderTitle] = useState('');
  const [dropTargetId, setDropTargetId] = useState('');
  const initializedFromArtifacts = useRef(false);
  const explorerRef = useRef<HTMLDivElement>(null);
  const materialInputRef = useRef<HTMLInputElement>(null);
  const [uploadingMaterials, setUploadingMaterials] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const uploadLessonRef = useRef<string | undefined>(undefined);
  const uploadMaterials = async (files: File[]) => {
    if (!files.length || uploadingMaterials) return;
    const targetLessonId = uploadLessonRef.current;
    const targetLesson = course.modules
      .flatMap((module) => module.lessons)
      .find((lesson) => lesson.id === targetLessonId);
    setUploadingMaterials(true);
    setUploadMessage('');
    let uploaded = 0;
    try {
      for (const file of files) {
        if (file.size > 80 * 1024 * 1024) throw new Error(`${file.name} 超过 80MB，无法上传`);
        const form = new FormData();
        form.append('file', file);
        const response = await fetch(`/api/course-space/${course.id}/materials`, {
          method: 'POST',
          body: form,
        });
        const result = await response.json();
        if (!response.ok || result.success === false)
          throw new Error(result.error || `上传 ${file.name} 失败`);
        uploaded += 1;
        if (targetLessonId) {
          const linked = await fetch(`/api/course-space/${course.id}/tree`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              action: 'move-item',
              itemKind: 'material',
              itemId: result.material.id,
              targetLessonId,
            }),
          });
          const linkResult = await linked.json();
          if (!linked.ok || linkResult.success === false)
            throw new Error(
              `${file.name} 已保存到课程资料，但归入周次失败：${linkResult.error || '请稍后重试'}`,
            );
        }
      }
      setUploadMessage(
        `已上传 ${uploaded} 份资料${targetLesson ? `至“${targetLesson.title}”` : ''}。`,
      );
    } catch (error) {
      setUploadMessage(
        `${uploaded ? `已上传 ${uploaded} 份资料；` : ''}${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      try {
        if (uploaded) {
          setOpenTemplates((items) => new Set(items).add('课程资料'));
          if (targetLessonId) {
            setCourseFilesExpanded(true);
            setExpandedLessons((items) => new Set(items).add(targetLessonId));
            setFolderView('AI课件');
            setScope({ type: 'lesson', lessonId: targetLessonId });
            onScopeChange?.({ type: 'lesson', lessonId: targetLessonId });
          } else setFolderView('课程资料');
          setSelectedFileId('');
          await onRefresh();
        }
      } catch {
        setUploadMessage('资料已上传，列表刷新失败，请刷新页面查看。');
      } finally {
        setUploadingMaterials(false);
        if (materialInputRef.current) materialInputRef.current.value = '';
      }
    }
  };
  const [treeWidth, setTreeWidth] = useState(320);
  useEffect(() => {
    if (!focusRequest) return;
    const next = focusRequest;
    setFolderView(
      next.folder === 'materials' ? '课程资料' : next.folder === 'outline' ? '课程大纲' : 'AI课件',
    );
    setSelectedFileId(next.fileId ?? '');
    setCourseFilesExpanded(true);
    setOpenTemplates((items) =>
      new Set(items).add(next.folder === 'materials' ? '课程资料' : '课程大纲'),
    );
    const target = course.modules.find((item) =>
      item.lessons.some(
        (lesson) =>
          lesson.id === next.lessonId || lesson.files?.some((file) => file.id === next.fileId),
      ),
    );
    const lesson = target?.lessons.find(
      (item) => item.id === next.lessonId || item.files?.some((file) => file.id === next.fileId),
    );
    if (target && lesson) {
      setScope({ type: 'lesson', lessonId: lesson.id });
      setExpanded((items) => new Set(items).add(target.id));
      setExpandedLessons((items) => new Set(items).add(lesson.id));
      onScopeChange?.({ type: 'lesson', lessonId: lesson.id });
    } else if (next.folder !== 'courseware') {
      setScope({ type: 'course' });
      onScopeChange?.({ type: 'course' });
    }
    explorerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    // Focus requests are explicit navigation events; background refreshes must not reset the teacher's selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRequest]);

  useEffect(() => {
    const saved = Number(window.localStorage.getItem('mentra.course-tree-width'));
    if (Number.isFinite(saved) && saved >= 160 && saved <= 480) setTreeWidth(saved);
  }, []);

  const startTreeResize = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = treeWidth;
    const move = (pointerEvent: PointerEvent) => {
      const containerWidth = explorerRef.current?.getBoundingClientRect().width ?? 1200;
      setTreeWidth(
        Math.round(
          Math.min(
            Math.max(160, startWidth + pointerEvent.clientX - startX),
            Math.min(480, containerWidth * 0.46),
          ),
        ),
      );
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      setTreeWidth((width) => {
        window.localStorage.setItem('mentra.course-tree-width', String(width));
        return width;
      });
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop, { once: true });
    window.addEventListener('pointercancel', stop, { once: true });
  };

  useEffect(() => {
    if (initializedFromArtifacts.current || artifacts.length === 0) return;
    initializedFromArtifacts.current = true;
    const preferred = [...artifacts].sort(
      (a, b) => artifactPriority(b) - artifactPriority(a) || b.updatedAt - a.updatedAt,
    )[0];
    if (preferred) setScope(preferred.scope);
  }, [artifacts]);
  useEffect(() => {
    if (!revealRequest) return;
    const frame = requestAnimationFrame(() => {
      const prefix = revealRequest.lessonId
        ? `[data-lesson-folder="${CSS.escape(revealRequest.lessonId)}"] `
        : '';
      const row = explorerRef.current?.querySelector<HTMLElement>(
        `${prefix}[data-file-location="${CSS.escape(revealRequest.id)}"]`,
      );
      row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      row?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [revealRequest]);
  const allFiles = useMemo<BrowserFile[]>(
    () => [
      ...artifacts.map((artifact) => ({
        id: artifact.id,
        title: artifact.title,
        kind: 'artifact' as const,
        artifact,
        scope: artifact.scope,
      })),
      ...course.materials.map((material) => {
        const lesson = course.modules
          .flatMap((module) => module.lessons)
          .find((item) => item.materialIds.includes(material.id));
        return {
          id: material.id,
          title: material.name,
          kind: 'material' as const,
          material,
          scope: lesson
            ? { type: 'lesson' as const, lessonId: lesson.id }
            : { type: 'course' as const },
        };
      }),
      ...course.modules.flatMap((module) =>
        module.lessons.flatMap((lesson) =>
          (lesson.files ?? []).map((courseFile) => ({
            id: courseFile.id,
            title: courseFile.title,
            kind: 'artifact' as const,
            courseFile,
            scope: { type: 'lesson' as const, lessonId: lesson.id },
          })),
        ),
      ),
    ],
    [artifacts, course.materials, course.modules],
  );
  const files = useMemo<BrowserFile[]>(() => {
    const latestCourseware = artifacts
      .filter((item) => item.type === 'lesson-courseware' && belongsToScope(item, scope, course))
      .sort((a, b) => artifactPriority(b) - artifactPriority(a) || b.updatedAt - a.updatedAt)[0];
    return latestCourseware
      ? [
          {
            id: latestCourseware.id,
            title: latestCourseware.title,
            kind: 'artifact',
            artifact: latestCourseware,
            scope,
          },
        ]
      : [];
  }, [artifacts, course, scope]);
  const explicitlySelectedArtifact = artifacts.find((item) => item.id === selectedFileId);
  const explicitlySelectedCourseFile = course.modules
    .flatMap((module) => module.lessons.flatMap((lesson) => lesson.files ?? []))
    .find((item) => item.id === selectedFileId);
  const explicitlySelectedMaterial = course.materials.find((item) => item.id === selectedFileId);
  const selectedFile: BrowserFile | undefined = explicitlySelectedArtifact
    ? {
        id: explicitlySelectedArtifact.id,
        title: explicitlySelectedArtifact.title,
        kind: 'artifact' as const,
        artifact: explicitlySelectedArtifact,
        scope: explicitlySelectedArtifact.scope,
      }
    : explicitlySelectedCourseFile
      ? {
          id: explicitlySelectedCourseFile.id,
          title: explicitlySelectedCourseFile.title,
          kind: 'artifact',
          courseFile: explicitlySelectedCourseFile,
          scope,
        }
      : explicitlySelectedMaterial
        ? {
            id: explicitlySelectedMaterial.id,
            title: explicitlySelectedMaterial.name,
            kind: 'material',
            material: explicitlySelectedMaterial,
            scope,
          }
        : folderView === 'AI课件'
          ? files[0]
          : undefined;
  useEffect(() => {
    if (folderView !== 'AI课件' || selectedFileId || scope.type !== 'lesson') return;
    const lesson = course.modules
      .flatMap((module) => module.lessons)
      .find((item) => item.id === scope.lessonId);
    const pending = ['lesson-objectives', 'knowledge-points']
      .map((type) => lesson?.files?.find((file) => file.type === type && file.status !== 'ready'))
      .find(Boolean);
    if (pending) setSelectedFileId(pending.id);
  }, [course.modules, folderView, scope, selectedFileId]);
  const [reviewContent, setReviewContent] = useState('');
  const [reviewBusy, setReviewBusy] = useState(false);
  useEffect(() => {
    setReviewContent(selectedFile?.courseFile?.content ?? selectedFile?.artifact?.content ?? '');
  }, [selectedFile?.id, selectedFile?.courseFile?.content, selectedFile?.artifact?.content]);
  const reviewSelected = async (approve: boolean) => {
    if (!selectedFile) return;
    setReviewBusy(true);
    try {
      const url = selectedFile.courseFile
        ? `/api/course-space/${course.id}/lesson-files/${selectedFile.id}`
        : `/api/course-space/${course.id}/artifacts/${selectedFile.id}`;
      const response = await fetch(url, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          action: approve ? 'approve' : 'save',
          ...(selectedFile.courseFile || editingFileId === selectedFile.id
            ? { content: reviewContent }
            : {}),
        }),
      });
      const result = await response.json();
      if (!response.ok || result.success === false) throw new Error(result.error || '保存审核失败');
      await onRefresh();
      setTreeMessage(approve ? '已审核通过。' : '修改已保存，待审核。');
      if (approve && selectedFile.courseFile) {
        const lesson = course.modules
          .flatMap((module) => module.lessons)
          .find((item) => item.id === selectedFile.courseFile?.lessonId);
        const next =
          selectedFile.courseFile.type === 'lesson-objectives'
            ? lesson?.files?.find((item) => item.type === 'knowledge-points')
            : undefined;
        const courseware = artifacts
          .filter(
            (item) =>
              item.type === 'lesson-courseware' &&
              item.scope.type === 'lesson' &&
              item.scope.lessonId === lesson?.id,
          )
          .sort((a, b) => b.updatedAt - a.updatedAt)[0];
        if (next || courseware) setSelectedFileId((next || courseware)!.id);
      }
    } catch (error) {
      setTreeMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setReviewBusy(false);
    }
  };
  const selectScope = (next: Scope) => {
    setFolderView('AI课件');
    setScope(next);
    setSelectedFileId('');
    onScopeChange?.(next);
  };
  const [publicationTarget, setPublicationTarget] = useState<PublicationTarget>();
  const publishFileToClass = async (
    target?: Pick<BrowserFile, 'artifact' | 'material' | 'courseFile'>,
  ) => {
    const file = target ?? selectedFile;
    if (!file) return;
    const artifact = file.artifact;
    const material = file.material;
    const lessonFile = file.courseFile;
    const resource = artifact ?? material ?? lessonFile;
    if (!resource) return;
    if (resource.classPublicationId && resource.publicationPlacement) {
      setTreeMessage('此文件已按确认的课时归属发布。');
      return;
    }
    setPublicationTarget({
      kind: artifact ? 'artifact' : material ? 'material' : 'course-file',
      id: resource.id,
      title: artifact?.title ?? material?.name ?? lessonFile!.title,
      lessonId:
        resource.publicationPlacement?.lessonId ??
        (artifact?.scope.type === 'lesson'
          ? artifact.scope.lessonId
          : (lessonFile?.lessonId ??
            course.modules
              .flatMap((module) => module.lessons)
              .find((lesson) => lesson.materialIds.includes(material?.id ?? ''))?.id)),
      resourceType:
        artifact?.type === 'lesson-courseware'
          ? 'courseware'
          : artifact?.type === 'course-outline'
            ? 'outline'
            : lessonFile?.type === 'lesson-objectives'
              ? 'objectives'
              : lessonFile?.type === 'knowledge-points'
                ? 'knowledge-points'
                : artifact?.type === 'exercise-set'
                  ? 'exercise'
                  : 'material',
      storageType: artifact?.classroomId
        ? '互动课堂课件'
        : material
          ? (material.name.split('.').pop()?.toUpperCase() ?? '原始文件')
          : '教学文档',
    });
  };
  const addModule = async (title: string) => {
    if (course.modules.some((module) => module.title.trim() === title.trim())) {
      setTreeMessage(`“${title.trim()}”已经存在，请使用其他模块名称。`);
      return;
    }
    const now = Date.now();
    const moduleId = `folder-${nanoid(10)}`;
    setSavingStructure(true);
    setTreeMessage('');
    try {
      await onCourseChange({
        ...course,
        updatedAt: now,
        modules: [
          ...course.modules,
          {
            id: moduleId,
            courseId: course.id,
            title: title.trim(),
            order: course.modules.length + 1,
            objectives: [],
            lessons: [],
            createdAt: now,
            updatedAt: now,
          },
        ],
      });
      setExpanded((items) => new Set(items).add(moduleId));
      selectScope({ type: 'module', moduleId });
      setNewFolder(undefined);
      setNewFolderTitle('');
      setTreeMessage(`已创建文件夹“${title.trim()}”。`);
    } catch (error) {
      setTreeMessage(`创建文件夹失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSavingStructure(false);
    }
  };
  const addLesson = async (moduleId: string, title: string) => {
    const target = course.modules.find((item) => item.id === moduleId);
    if (!target) return;
    if (target.lessons.some((lesson) => lesson.title.trim() === title.trim())) {
      setTreeMessage(`“${title.trim()}”已经存在，请使用其他文件夹名称。`);
      return;
    }
    const now = Date.now();
    const lessonId = nanoid(10);
    setSavingStructure(true);
    setTreeMessage('');
    try {
      await onCourseChange({
        ...course,
        updatedAt: now,
        modules: course.modules.map((item) =>
          item.id === moduleId
            ? {
                ...item,
                updatedAt: now,
                lessons: [
                  ...item.lessons,
                  {
                    id: lessonId,
                    moduleId,
                    week: target.week,
                    lessonNumber: target.week ? target.lessons.length + 1 : undefined,
                    teachingHours: target.week
                      ? course.curriculum?.teachingHoursPerLesson
                      : undefined,
                    title: title.trim(),
                    order: item.lessons.length + 1,
                    objectives: [],
                    materialIds: [],
                    createdAt: now,
                    updatedAt: now,
                  },
                ],
              }
            : item,
        ),
      });
      setExpanded((items) => new Set(items).add(moduleId));
      setExpandedLessons((items) => new Set(items).add(lessonId));
      selectScope({ type: 'lesson', lessonId });
      setNewFolder(undefined);
      setNewFolderTitle('');
      setTreeMessage(`已创建文件夹“${title.trim()}”。`);
    } catch (error) {
      setTreeMessage(`创建文件夹失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSavingStructure(false);
    }
  };
  const addCoursewareFolder = async (title: string) => {
    if (course.modules.some((item) => item.workspaceKind === 'week')) {
      if (course.modules.some((item) => item.title.trim() === title.trim())) {
        setTreeMessage('该文件夹名称已存在');
        return;
      }
      const now = Date.now();
      const moduleId = nanoid(12);
      setSavingStructure(true);
      try {
        await onCourseChange({
          ...course,
          updatedAt: now,
          modules: [
            ...course.modules,
            {
              id: moduleId,
              courseId: course.id,
              title: title.trim(),
              workspaceKind: 'week',
              week: Number(title.match(/第\s*(\d+)\s*周/u)?.[1]) || undefined,
              order: course.modules.length + 1,
              objectives: [],
              lessons: [],
              createdAt: now,
              updatedAt: now,
            },
          ],
        });
        setCourseFilesExpanded(true);
        setExpanded((items) => new Set(items).add(moduleId));
        selectScope({ type: 'module', moduleId });
        setNewFolder(undefined);
        setNewFolderTitle('');
      } catch (error) {
        setTreeMessage(error instanceof Error ? error.message : String(error));
      } finally {
        setSavingStructure(false);
      }
      return;
    }

    if (
      course.modules
        .filter((module) => !module.id.startsWith('folder-'))
        .some((module) => module.lessons.some((lesson) => lesson.title.trim() === title.trim()))
    ) {
      setTreeMessage(`“${title.trim()}”已经存在，请使用其他文件夹名称。`);
      return;
    }
    const target = course.modules.find((module) => !module.id.startsWith('folder-'));
    if (target) return addLesson(target.id, title);
    const now = Date.now();
    const moduleId = nanoid(10);
    const lessonId = nanoid(10);
    setSavingStructure(true);
    setTreeMessage('');
    try {
      await onCourseChange({
        ...course,
        updatedAt: now,
        modules: [
          ...course.modules,
          {
            id: moduleId,
            courseId: course.id,
            title: 'AI课件',
            order: course.modules.length + 1,
            objectives: [],
            createdAt: now,
            updatedAt: now,
            lessons: [
              {
                id: lessonId,
                moduleId,
                title: title.trim(),
                order: 1,
                objectives: [],
                materialIds: [],
                createdAt: now,
                updatedAt: now,
              },
            ],
          },
        ],
      });
      setCourseFilesExpanded(true);
      setExpandedLessons((items) => new Set(items).add(lessonId));
      selectScope({ type: 'lesson', lessonId });
      setNewFolder(undefined);
      setNewFolderTitle('');
    } catch (error) {
      setTreeMessage(`创建文件夹失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSavingStructure(false);
    }
  };
  const createStructureWithAgent = async () => {
    const message = window.prompt(
      '告诉课程操作智能体要创建什么，例如：\n生成1-17周的课件，并在课件生成模块下建立对应课时文件夹',
    );
    if (!message?.trim()) return;
    const planned = await fetch(`/api/course-space/${course.id}/agent`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message, sessionId: `teacher-${course.id}-default` }),
    });
    const plannedResult = (await planned.json()) as {
      success?: boolean;
      error?: string;
      text?: string;
      plan?: TeacherOperationPlan;
    };
    if (!planned.ok || !plannedResult.plan) {
      window.alert(plannedResult.error || plannedResult.text || '智能体未形成可执行的课程结构计划');
      return;
    }
    if (
      !window.confirm(
        `${plannedResult.plan.title}\n\n${plannedResult.plan.summary}\n\n确认执行吗？`,
      )
    )
      return;
    const executed = await fetch(`/api/course-space/${course.id}/agent/operations`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ plan: plannedResult.plan }),
    });
    const executedResult = (await executed.json()) as {
      success?: boolean;
      error?: string;
      plan?: { result?: string };
    };
    if (!executed.ok) {
      window.alert(executedResult.error || '课程结构创建失败');
      return;
    }
    await onRefresh();
    window.alert(executedResult.plan?.result || '课程结构已更新');
  };
  const runTreeAction = async (body: Record<string, unknown>) => {
    setSavingStructure(true);
    setTreeMessage('');
    try {
      const response = await fetch(`/api/course-space/${course.id}/tree`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = (await response.json().catch(() => undefined)) as
        | { error?: string }
        | undefined;
      if (!response.ok) throw new Error(result?.error || '课程目录操作失败');
      setSelectedFileId('');
      await onRefresh();
      return true;
    } catch (error) {
      setTreeMessage(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setSavingStructure(false);
      setDropTargetId('');
    }
  };
  const startDragging = (event: React.DragEvent<HTMLElement>, item: DragItem) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/x-mentra-course-item', JSON.stringify(item));
  };
  const showMovedFile = (lessonId: string, fileId: string) => {
    selectScope({ type: 'lesson', lessonId });
    setSelectedFileId(fileId);
    const parent = course.modules.find((module) =>
      module.lessons.some((lesson) => lesson.id === lessonId),
    );
    if (parent) setExpanded((items) => new Set(items).add(parent.id));
    setExpandedLessons((items) => new Set(items).add(lessonId));
    setTreeMessage('文件已移动到目标课时文件夹。');
  };
  const dropIntoLesson = async (event: React.DragEvent<HTMLElement>, lessonId: string) => {
    event.preventDefault();
    setDropTargetId('');
    if (savingStructure) return;
    const raw = event.dataTransfer.getData('application/x-mentra-course-item');
    if (!raw) return;
    try {
      const item = JSON.parse(raw) as DragItem;
      const succeeded = await runTreeAction({
        action: 'move-item',
        itemKind: item.kind,
        itemId: item.id,
        targetLessonId: lessonId,
      });
      if (succeeded) {
        showMovedFile(lessonId, item.id);
      }
    } catch {
      setTreeMessage('拖拽数据无效，请重新操作。');
    }
  };
  const revealFile = (file: BrowserFile) => {
    const folder =
      file.material?.purpose === 'course-outline' || file.artifact?.type === 'course-outline'
        ? '课程大纲'
        : file.material && file.scope.type === 'course'
          ? '课程资料'
          : 'AI课件';
    setFolderView(folder);
    setSelectedFileId(file.id);
    setScope(file.scope);
    onScopeChange?.(file.scope);
    if (folder !== 'AI课件') setOpenTemplates((items) => new Set(items).add(folder));
    else {
      setCourseFilesExpanded(true);
      if (file.scope.type === 'lesson') {
        const lessonId = file.scope.lessonId;
        const parent = course.modules.find((module) =>
          module.lessons.some((lesson) => lesson.id === lessonId),
        );
        if (parent) setExpanded((items) => new Set(items).add(parent.id));
        setExpandedLessons((items) => new Set(items).add(lessonId));
      }
    }
    setRevealRequest({
      id: file.id,
      nonce: Date.now(),
      lessonId:
        folder === 'AI课件' && file.scope.type === 'lesson' ? file.scope.lessonId : undefined,
    });
    setTreeMessage(`已定位“${file.title}”。`);
  };
  const editFile = (file: BrowserFile) => {
    revealFile(file);
    setRevealRequest(undefined);
    if (file.material) setSourceEditId(file.id);
    else {
      setEditingFileId(file.id);
      setTreeMessage(
        file.artifact?.classroomUrl
          ? '已打开课件编辑器，可直接修改幻灯片、讲稿和动作。'
          : '编辑正文后点击“保存修改”。',
      );
    }
  };
  const filesById = useMemo(() => new Map(allFiles.map((file) => [file.id, file])), [allFiles]);
  const renderFileActions = (id: string, children?: ReactNode, location = true) => {
    const file = filesById.get(id);
    if (!file) return null;
    const resource = file.artifact ?? file.material ?? file.courseFile!;
    return (
      <div key={id} className="min-w-0" data-file-location={location && children ? id : undefined}>
        <ResourceActions
          courseId={course.id}
          course={course}
          presentation="menu"
          kind={file.artifact ? 'artifacts' : file.material ? 'materials' : 'lesson-files'}
          id={id}
          title={file.title}
          pinned={resource.pinned}
          published={Boolean(resource.classPublicationId) || file.artifact?.status === 'published'}
          courseActive={course.status === 'active'}
          onChange={onRefresh}
          onEdit={() => editFile(file)}
          onReveal={() => revealFile(file)}
          onPublish={() => void publishFileToClass(file)}
          onMoved={(lessonId) => showMovedFile(lessonId, id)}
          onDeleted={async () => {
            if (selectedFile?.id === id) {
              setSelectedFileId('');
              setEditingFileId('');
            }
            await onRefresh();
          }}
        >
          {children}
        </ResourceActions>
      </div>
    );
  };
  const revealFolder = (kind: 'modules' | 'lessons', id: string) => {
    setCourseFilesExpanded(true);
    if (kind === 'modules') {
      selectScope({ type: 'module', moduleId: id });
      setExpanded((items) => new Set(items).add(id));
    } else {
      selectScope({ type: 'lesson', lessonId: id });
      const parent = course.modules.find((module) =>
        module.lessons.some((lesson) => lesson.id === id),
      );
      if (parent) setExpanded((items) => new Set(items).add(parent.id));
      setExpandedLessons((items) => new Set(items).add(id));
    }
    setRevealRequest({ id, nonce: Date.now() });
  };
  const renderFolderActions = (
    kind: 'modules' | 'lessons',
    item: { id: string; title: string; pinned?: boolean },
    children: ReactNode,
    location = true,
  ) => (
    <div
      key={item.id}
      className="min-w-0 flex-1"
      data-file-location={location ? item.id : undefined}
    >
      <ResourceActions
        courseId={course.id}
        presentation="menu"
        kind={kind}
        id={item.id}
        title={item.title}
        pinned={item.pinned}
        published={false}
        courseActive={course.status === 'active'}
        onChange={onRefresh}
        onReveal={() => revealFolder(kind, item.id)}
        onDeleted={async () => {
          selectScope({ type: 'course' });
          await onRefresh();
        }}
      >
        {children}
      </ResourceActions>
    </div>
  );
  const pinnedFiles = allFiles.filter(
    (file) => (file.artifact ?? file.material ?? file.courseFile)?.pinned,
  );
  const pinnedFolders = course.modules.flatMap((module) => [
    ...(module.pinned ? [{ kind: 'modules' as const, item: module }] : []),
    ...module.lessons
      .filter((lesson) => lesson.pinned)
      .map((item) => ({ kind: 'lessons' as const, item })),
  ]);
  const textEditing =
    selectedFile &&
    editingFileId === selectedFile.id &&
    !selectedFile.material &&
    !selectedFile.artifact?.classroomUrl &&
    !(selectedFile.artifact ?? selectedFile.courseFile)?.classPublicationId;
  const currentFile = selectedFile ? filesById.get(selectedFile.id) : undefined;
  const currentModule =
    currentFile &&
    course.modules.find((module) =>
      currentFile.scope.type === 'module'
        ? module.id === currentFile.scope.moduleId
        : currentFile.scope.type === 'lesson' &&
          module.lessons.some(
            (lesson) =>
              currentFile.scope.type === 'lesson' && lesson.id === currentFile.scope.lessonId,
          ),
    );
  const currentLesson =
    currentFile?.scope.type === 'lesson'
      ? currentModule?.lessons.find(
          (lesson) =>
            currentFile.scope.type === 'lesson' && lesson.id === currentFile.scope.lessonId,
        )
      : undefined;
  const locationLabel = [course.title, currentModule?.title, currentLesson?.title]
    .filter(Boolean)
    .join(' / ');

  return (
    <div className="overflow-hidden rounded-[26px] border border-white/80 bg-white/90 shadow-[0_28px_80px_-42px_rgba(15,23,42,.45)] backdrop-blur-xl">
      {/* Course tree + the real OpenMAIC Pro workspace. The embedded classroom
        owns the per-page outline rail and narration/action timeline. */}
      <div
        ref={explorerRef}
        className="grid min-h-0"
        style={{ height, gridTemplateColumns: `${treeWidth}px 8px minmax(0, 1fr)` }}
      >
        <aside className="min-h-0 overflow-y-auto bg-[#faf8fb] p-3">
          <div className="mb-3 rounded-xl bg-[#B00055] px-3 py-3 text-white">
            <div className="flex items-center gap-2">
              <BookOpen className="size-4" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{course.title}</p>
                <p className="text-[10px] text-white/65">课程文件空间</p>
              </div>
              <button
                title="让智能体创建课程结构"
                aria-label="让智能体创建课程结构"
                onClick={() => void createStructureWithAgent()}
                className="grid size-7 shrink-0 place-items-center rounded-lg bg-white/15 hover:bg-white/25"
              >
                <Sparkles className="size-3.5" />
              </button>
            </div>
          </div>
          {(pinnedFiles.length > 0 || pinnedFolders.length > 0) && (
            <section aria-label="置顶项目" className="mb-4 border-b border-slate-200 pb-3">
              <p className="mb-2 flex items-center gap-2 px-2 text-[11px] font-medium text-slate-500">
                <Pin className="size-3" />
                置顶<span className="ml-auto">{pinnedFiles.length + pinnedFolders.length}</span>
              </p>
              {pinnedFolders.map(({ kind, item }) =>
                renderFolderActions(
                  kind,
                  item,
                  <button
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs hover:bg-[#B00055]/5"
                    onClick={() => revealFolder(kind, item.id)}
                  >
                    <Folder className="size-3.5 shrink-0 text-amber-500" />
                    <span className="truncate">{item.title}</span>
                  </button>,
                  false,
                ),
              )}
              {pinnedFiles.map((file) =>
                renderFileActions(
                  file.id,
                  <button
                    className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${selectedFile?.id === file.id ? 'bg-[#B00055]/10 text-[#8F0046]' : 'hover:bg-[#B00055]/5'}`}
                    title={file.title}
                    onClick={() => {
                      setSelectedFileId(file.id);
                      setScope(file.scope);
                    }}
                  >
                    <FileText className="size-3.5 shrink-0 text-[#B00055]" />
                    <span className="truncate">{file.title}</span>
                  </button>,
                  false,
                ),
              )}
            </section>
          )}
          <input
            ref={materialInputRef}
            type="file"
            multiple
            className="hidden"
            aria-label="选择课程资料"
            disabled={uploadingMaterials}
            onChange={(event) => void uploadMaterials(Array.from(event.target.files ?? []))}
          />
          {uploadMessage && (
            <p
              role="status"
              className="mb-2 rounded-lg border bg-white px-2.5 py-2 text-[11px] text-slate-600"
            >
              {uploadMessage}
            </p>
          )}
          {['课程资料', '课程大纲'].map((title) => {
            const entries =
              title === '课程资料'
                ? course.materials
                    .filter((item) => item.purpose !== 'course-outline')
                    .map((item) => ({ id: item.id, title: item.name }))
                : [
                    ...course.materials
                      .filter((item) => item.purpose === 'course-outline')
                      .map((item) => ({ id: item.id, title: `原始大纲 · ${item.name}` })),
                    ...artifacts
                      .filter((item) => item.type === 'course-outline')
                      .map((item) => ({ id: item.id, title: item.title })),
                  ];
            const open = openTemplates.has(title);
            return (
              <div key={title} className="mb-2">
                <div className="flex items-center gap-1">
                  <button
                    aria-label={`${open ? '收起' : '展开'}${title}`}
                    className="p-1 text-slate-400"
                    onClick={() =>
                      setOpenTemplates((items) => {
                        const next = new Set(items);
                        if (next.has(title)) next.delete(title);
                        else next.add(title);
                        return next;
                      })
                    }
                  >
                    {open ? (
                      <ChevronDown className="size-3.5" />
                    ) : (
                      <ChevronRight className="size-3.5" />
                    )}
                  </button>
                  <button
                    onClick={() => {
                      setFolderView(title);
                      setSelectedFileId('');
                      onScopeChange?.({ type: 'course' });
                    }}
                    className={`flex flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${folderView === title && !selectedFileId ? 'bg-[#B00055]/10 text-[#8F0046]' : 'hover:bg-slate-100'}`}
                  >
                    <Folder className="size-4 text-[#B00055]" />
                    {title}
                    <span className="ml-auto text-[10px] text-slate-400">{entries.length}</span>
                  </button>
                  {title === '课程资料' && (
                    <button
                      type="button"
                      title="资料上传（单个文件不超过80MB，可多选）"
                      aria-label="资料上传"
                      disabled={uploadingMaterials}
                      onClick={() => {
                        uploadLessonRef.current = undefined;
                        materialInputRef.current?.click();
                      }}
                      className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1.5 text-[10px] text-[#B00055] hover:bg-[#B00055]/10 disabled:opacity-50"
                    >
                      <Upload className="size-3.5" />
                      {treeWidth >= 280 && (uploadingMaterials ? '上传中…' : '资料上传')}
                    </button>
                  )}
                </div>
                {open && (
                  <div className="ml-6 space-y-1 border-l pl-2">
                    {entries.length ? (
                      entries.map((entry) =>
                        renderFileActions(
                          entry.id,
                          <button
                            key={entry.id}
                            title={entry.title}
                            draggable
                            onDragStart={(event) =>
                              startDragging(event, {
                                kind: course.materials.some((item) => item.id === entry.id)
                                  ? 'material'
                                  : 'artifact',
                                id: entry.id,
                              })
                            }
                            onClick={() => {
                              setFolderView(title);
                              setSelectedFileId(entry.id);
                            }}
                            className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[11px] ${selectedFileId === entry.id ? 'bg-[#B00055]/10 text-[#8F0046]' : 'text-slate-600 hover:bg-slate-100'}`}
                          >
                            <FileText className="size-3.5 shrink-0 text-blue-500" />
                            <span className="truncate">{entry.title}</span>
                          </button>,
                        ),
                      )
                    ) : (
                      <p className="px-2 py-2 text-[11px] text-slate-400">暂无{title}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          <div className="mb-1 flex items-center gap-1">
            <button
              className="p-1 text-slate-400"
              onClick={() => setCourseFilesExpanded((value) => !value)}
            >
              {courseFilesExpanded ? (
                <ChevronDown className="size-3.5" />
              ) : (
                <ChevronRight className="size-3.5" />
              )}
            </button>
            <button
              onClick={() => selectScope({ type: 'course' })}
              className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${scope.type === 'course' && !selectedFileId ? 'bg-[#B00055]/10 text-[#8F0046]' : 'hover:bg-slate-100'}`}
            >
              <Folder className="size-4" />
              AI课件
            </button>
            <button
              title="在AI课件下创建子文件夹"
              aria-label="在AI课件下创建子文件夹"
              onClick={() => {
                setCourseFilesExpanded(true);
                setNewFolder({ kind: 'courseware' });
                setNewFolderTitle('');
              }}
              disabled={savingStructure}
              className="grid size-7 shrink-0 place-items-center rounded-lg border bg-white text-[#B00055] hover:bg-[#B00055]/5"
            >
              <Plus className="size-3.5" />
            </button>
          </div>
          {courseFilesExpanded && (
            <div className="mb-2 ml-6 max-h-56 space-y-0.5 overflow-y-auto border-l pl-2">
              {artifacts
                .filter(
                  (artifact) =>
                    artifact.type !== 'course-outline' && artifact.scope.type !== 'lesson',
                )
                .map((artifact) =>
                  renderFileActions(
                    artifact.id,
                    <button
                      key={artifact.id}
                      draggable
                      onDragStart={(event) =>
                        startDragging(event, { kind: 'artifact', id: artifact.id })
                      }
                      title={artifact.title}
                      onClick={() => {
                        setFolderView('AI课件');
                        setScope(artifact.scope);
                        setSelectedFileId(artifact.id);
                      }}
                      className={`flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === artifact.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-600 hover:bg-slate-100'}`}
                    >
                      {artifact.classroomUrl ? (
                        <Presentation className="size-3.5 shrink-0 text-[#B00055]" />
                      ) : (
                        <FileText className="size-3.5 shrink-0 text-blue-500" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{artifact.title}</span>
                      {showOriginBadges && (
                        <span className="ml-5 flex basis-full items-center gap-1">
                          <OriginBadge origin="agent" />
                          <ClassPublicationBadge
                            publicationId={
                              course.status === 'active' && artifact.status === 'published'
                                ? artifact.classPublicationId
                                : undefined
                            }
                            onPublish={
                              course.status === 'active'
                                ? () => void publishFileToClass({ artifact })
                                : undefined
                            }
                          />
                        </span>
                      )}
                    </button>,
                  ),
                )}
            </div>
          )}
          <div className="space-y-1">
            {treeMessage && (
              <div className="mb-2 rounded-lg border border-[#B00055]/15 bg-white px-2.5 py-2 text-[11px] leading-4 text-slate-600">
                {treeMessage}
              </div>
            )}
            {course.modules
              .filter((module) => courseFilesExpanded || module.id.startsWith('folder-'))
              .map((module) => (
                <div
                  key={module.id}
                  className={module.id.startsWith('folder-') ? '' : 'ml-6 border-l pl-2'}
                >
                  {(module.id.startsWith('folder-') || module.workspaceKind === 'week') && (
                    <div className="group/module flex items-center">
                      <button
                        className="p-1 text-slate-400"
                        onClick={() =>
                          setExpanded((items) => {
                            const next = new Set(items);
                            if (next.has(module.id)) next.delete(module.id);
                            else next.add(module.id);
                            return next;
                          })
                        }
                      >
                        {expanded.has(module.id) ? (
                          <ChevronDown className="size-3.5" />
                        ) : (
                          <ChevronRight className="size-3.5" />
                        )}
                      </button>
                      {renderFolderActions(
                        'modules',
                        module,
                        <button
                          onClick={() => selectScope({ type: 'module', moduleId: module.id })}
                          className={`flex w-full min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${scope.type === 'module' && scope.moduleId === module.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'hover:bg-slate-100'}`}
                        >
                          <Folder className="size-4 shrink-0 text-amber-500" />
                          <span className="truncate">{module.title}</span>
                        </button>,
                      )}
                      <button
                        title={`在“${module.title}”下添加课时文件夹`}
                        aria-label={`在“${module.title}”下添加课时文件夹`}
                        onClick={() => {
                          setNewFolder({ kind: 'lesson', moduleId: module.id });
                          setNewFolderTitle('');
                        }}
                        disabled={savingStructure}
                        className="mr-1 grid size-6 shrink-0 place-items-center rounded-md text-slate-400 opacity-60 hover:bg-[#B00055]/10 hover:text-[#B00055] group-hover/module:opacity-100"
                      >
                        <Plus className="size-3.5" />
                      </button>
                    </div>
                  )}
                  {((!module.id.startsWith('folder-') && module.workspaceKind !== 'week') ||
                    expanded.has(module.id)) && (
                    <div
                      className={
                        module.id.startsWith('folder-') || module.workspaceKind === 'week'
                          ? 'ml-6 border-l pl-2'
                          : ''
                      }
                    >
                      {[...module.lessons]
                        .sort((a, b) => a.order - b.order)
                        .map((lesson) => {
                          const artifactFiles = artifacts.filter(
                            (artifact) =>
                              artifact.scope.type === 'lesson' &&
                              artifact.scope.lessonId === lesson.id,
                          );
                          const structureFiles = [...(lesson.files ?? [])].sort((a, b) => {
                            const rank = (type: string) =>
                              type === 'lesson-objectives'
                                ? 0
                                : type === 'knowledge-points'
                                  ? 1
                                  : 2;
                            return rank(a.type) - rank(b.type);
                          });
                          const lessonMaterials = course.materials.filter((material) =>
                            lesson.materialIds.includes(material.id),
                          );
                          const fileCount =
                            artifactFiles.length + structureFiles.length + lessonMaterials.length;
                          const isExpanded = expandedLessons.has(lesson.id);
                          return (
                            <div key={lesson.id} data-lesson-folder={lesson.id}>
                              <div className="group/lesson flex items-center">
                                <button
                                  className="p-1 text-slate-400"
                                  aria-label={`${isExpanded ? '收起' : '展开'}“${lesson.title}”`}
                                  onClick={() =>
                                    setExpandedLessons((items) => {
                                      const next = new Set(items);
                                      if (next.has(lesson.id)) next.delete(lesson.id);
                                      else next.add(lesson.id);
                                      return next;
                                    })
                                  }
                                >
                                  {isExpanded ? (
                                    <ChevronDown className="size-3" />
                                  ) : (
                                    <ChevronRight className="size-3" />
                                  )}
                                </button>
                                {renderFolderActions(
                                  'lessons',
                                  lesson,
                                  <button
                                    onClick={() => {
                                      selectScope({ type: 'lesson', lessonId: lesson.id });
                                      setExpandedLessons((items) => new Set(items).add(lesson.id));
                                    }}
                                    onDragOver={(event) => {
                                      event.preventDefault();
                                      event.dataTransfer.dropEffect = 'move';
                                      setDropTargetId(lesson.id);
                                    }}
                                    onDragLeave={() => setDropTargetId('')}
                                    onDrop={(event) => void dropIntoLesson(event, lesson.id)}
                                    className={`my-0.5 flex w-full min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-2 text-left text-xs ${dropTargetId === lesson.id ? 'ring-2 ring-[#B00055]/40 bg-[#B00055]/10' : ''} ${scope.type === 'lesson' && scope.lessonId === lesson.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-600 hover:bg-slate-100'}`}
                                  >
                                    <Folder className="size-3.5 shrink-0 text-[#B00055]" />
                                    <span className="truncate">{lesson.title}</span>
                                    {fileCount > 0 && (
                                      <span className="ml-auto text-[10px] text-slate-400">
                                        {fileCount}
                                      </span>
                                    )}
                                  </button>,
                                )}
                                <button
                                  type="button"
                                  title={`上传资料至“${lesson.title}”`}
                                  aria-label={`上传资料至${lesson.title}`}
                                  disabled={uploadingMaterials}
                                  onClick={() => {
                                    uploadLessonRef.current = lesson.id;
                                    materialInputRef.current?.click();
                                  }}
                                  className="ml-1 flex shrink-0 items-center gap-1 rounded-lg px-1.5 py-1.5 text-[10px] text-[#B00055] hover:bg-[#B00055]/10 disabled:opacity-50"
                                >
                                  <Upload className="size-3.5" />
                                  {treeWidth >= 300 && '上传资料'}
                                </button>
                              </div>
                              {isExpanded && fileCount > 0 && (
                                <div className="ml-5 border-l pl-2">
                                  {lessonMaterials.map((material) =>
                                    renderFileActions(
                                      material.id,
                                      <button
                                        key={material.id}
                                        draggable
                                        onDragStart={(event) =>
                                          startDragging(event, {
                                            kind: 'material',
                                            id: material.id,
                                          })
                                        }
                                        title={material.name}
                                        onClick={() => {
                                          setScope({ type: 'lesson', lessonId: lesson.id });
                                          setSelectedFileId(material.id);
                                        }}
                                        className={`my-0.5 flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === material.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
                                      >
                                        <Presentation className="size-3.5 shrink-0 text-orange-500" />
                                        <span className="min-w-0 flex-1 truncate">
                                          {material.name}
                                        </span>
                                        {showOriginBadges && (
                                          <span className="ml-5 flex basis-full items-center gap-1">
                                            <OriginBadge origin="teacher" />
                                            <ClassPublicationBadge
                                              publicationId={
                                                course.status === 'active'
                                                  ? material.classPublicationId
                                                  : undefined
                                              }
                                              onPublish={
                                                course.status === 'active'
                                                  ? () => void publishFileToClass({ material })
                                                  : undefined
                                              }
                                            />
                                          </span>
                                        )}
                                      </button>,
                                    ),
                                  )}
                                  {structureFiles.map((file) =>
                                    renderFileActions(
                                      file.id,
                                      <button
                                        key={file.id}
                                        draggable
                                        onDragStart={(event) =>
                                          startDragging(event, { kind: 'course-file', id: file.id })
                                        }
                                        title={file.title}
                                        onClick={() => {
                                          setScope({ type: 'lesson', lessonId: lesson.id });
                                          setSelectedFileId(file.id);
                                        }}
                                        className={`my-0.5 flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === file.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
                                      >
                                        <FileText className="size-3.5 shrink-0 text-blue-500" />
                                        <span className="min-w-0 flex-1 truncate">
                                          {file.title}
                                        </span>
                                        <span className="shrink-0 whitespace-nowrap text-[9px] text-slate-400">
                                          {file.status === 'ready' ? '已审核' : '待审核'}
                                        </span>
                                        {showOriginBadges && (
                                          <span className="ml-5 flex basis-full items-center gap-1">
                                            <OriginBadge origin="agent" />
                                            <ClassPublicationBadge
                                              publicationId={
                                                course.status === 'active'
                                                  ? file.classPublicationId
                                                  : undefined
                                              }
                                              onPublish={
                                                course.status === 'active'
                                                  ? () =>
                                                      void publishFileToClass({ courseFile: file })
                                                  : undefined
                                              }
                                            />
                                          </span>
                                        )}
                                      </button>,
                                    ),
                                  )}
                                  {artifactFiles.map((artifact) =>
                                    renderFileActions(
                                      artifact.id,
                                      <button
                                        key={artifact.id}
                                        draggable
                                        onDragStart={(event) =>
                                          startDragging(event, {
                                            kind: 'artifact',
                                            id: artifact.id,
                                          })
                                        }
                                        title={artifact.title}
                                        onClick={() => {
                                          setScope({ type: 'lesson', lessonId: lesson.id });
                                          setSelectedFileId(artifact.id);
                                        }}
                                        className={`my-0.5 flex w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === artifact.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
                                      >
                                        {artifact.classroomUrl ? (
                                          <Presentation className="size-3.5 shrink-0 text-[#B00055]" />
                                        ) : (
                                          <FileText className="size-3.5 shrink-0 text-blue-500" />
                                        )}
                                        <span className="min-w-0 flex-1 truncate">
                                          {artifact.title}
                                        </span>
                                        {showOriginBadges && (
                                          <span className="ml-5 flex basis-full items-center gap-1">
                                            <OriginBadge origin="agent" />
                                            <ClassPublicationBadge
                                              publicationId={
                                                course.status === 'active' &&
                                                artifact.status === 'published'
                                                  ? artifact.classPublicationId
                                                  : undefined
                                              }
                                              onPublish={
                                                course.status === 'active'
                                                  ? () => void publishFileToClass({ artifact })
                                                  : undefined
                                              }
                                            />
                                          </span>
                                        )}
                                      </button>,
                                    ),
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                    </div>
                  )}
                </div>
              ))}
          </div>
          <button
            onClick={() => {
              setNewFolder({ kind: 'module' });
              setNewFolderTitle('');
            }}
            disabled={savingStructure}
            className="mt-3 flex w-full items-center gap-2 rounded-lg border border-dashed border-[#B00055]/30 px-3 py-2.5 text-xs text-[#B00055] hover:bg-[#B00055]/5 disabled:opacity-50"
          >
            <Plus className="size-4" />
            创建文件夹
          </button>
        </aside>
        <div
          role="separator"
          aria-label="调整课程目录宽度"
          aria-orientation="vertical"
          aria-valuemin={160}
          aria-valuemax={480}
          aria-valuenow={treeWidth}
          tabIndex={0}
          onPointerDown={startTreeResize}
          onKeyDown={(event) => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
            event.preventDefault();
            setTreeWidth((width) => {
              const next = Math.min(
                480,
                Math.max(160, width + (event.key === 'ArrowRight' ? 16 : -16)),
              );
              window.localStorage.setItem('mentra.course-tree-width', String(next));
              return next;
            });
          }}
          className="group relative z-10 cursor-col-resize touch-none border-x border-slate-200 bg-white/80 outline-none hover:bg-[#B00055]/10 focus:bg-[#B00055]/10"
        >
          <GripVertical className="absolute left-1/2 top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 text-slate-300 group-hover:text-[#B00055] group-focus:text-[#B00055]" />
        </div>
        <section className="flex min-h-0 min-w-0 flex-col bg-[#f5f6f8]">
          <div className="flex min-h-11 shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-white px-4 py-1.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium text-slate-700">
                {selectedFile?.title || folderView}
              </p>
              {currentFile && (
                <button
                  onClick={() => revealFile(currentFile)}
                  title={`打开文件位置：${locationLabel}`}
                  className="mt-0.5 flex max-w-full items-center gap-1 text-[10px] text-slate-500 hover:text-[#B00055]"
                >
                  <FolderOpen className="size-3 shrink-0" />
                  <span className="truncate">{locationLabel}</span>
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {selectedFile &&
                (selectedFile.courseFile?.classPublicationId ||
                  selectedFile.artifact?.classPublicationId ||
                  selectedFile.material?.classPublicationId) &&
                !(selectedFile.artifact ?? selectedFile.material ?? selectedFile.courseFile)
                  ?.publicationPlacement && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={course.status !== 'active'}
                    onClick={() => void publishFileToClass()}
                  >
                    确认课时归属并发布
                  </Button>
                )}
              {(selectedFile?.courseFile || textEditing) &&
                !(selectedFile?.courseFile ?? selectedFile?.artifact)?.classPublicationId && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={reviewBusy}
                    onClick={() => void reviewSelected(false)}
                  >
                    保存修改
                  </Button>
                )}
              {(selectedFile?.courseFile || selectedFile?.artifact) &&
                !selectedFile?.courseFile?.classPublicationId &&
                selectedFile?.artifact?.status !== 'published' && (
                  <Button size="sm" disabled={reviewBusy} onClick={() => void reviewSelected(true)}>
                    审核通过{selectedFile?.courseFile ? '，下一项' : ''}
                  </Button>
                )}
              {selectedFile && renderFileActions(selectedFile.id)}
              {selectedFile?.artifact?.classroomUrl && (
                <Button size="sm" variant="outline" asChild>
                  <a
                    href={withTeacherReturn(
                      selectedFile.artifact.classroomUrl,
                      courseWorkspaceUrl(course.id),
                    )}
                    target="_blank"
                    rel="noreferrer"
                  >
                    全屏打开
                    <ExternalLink className="ml-1 size-3.5" />
                  </a>
                </Button>
              )}
            </div>
          </div>
          <div className="min-h-0 flex-1 p-2">
            {textEditing ? (
              <div className="flex h-full flex-col rounded-xl border bg-white p-5 shadow-sm">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="truncate text-lg font-semibold">{selectedFile.title}</h2>
                  <Button size="sm" variant="outline" onClick={() => setEditingFileId('')}>
                    查看预览
                  </Button>
                </div>
                <p className="mb-3 text-xs text-slate-500">
                  编辑正文后保存修改；支持 Markdown 标题和列表。
                </p>
                <textarea
                  autoFocus
                  aria-label="编辑文件内容"
                  value={reviewContent}
                  onChange={(event) => setReviewContent(event.target.value)}
                  className="min-h-0 flex-1 resize-none rounded-lg border p-4 font-mono text-sm leading-7 outline-none focus:border-[#B00055]"
                />
              </div>
            ) : selectedFile?.artifact?.classroomUrl ? (
              <iframe
                title={selectedFile.title}
                src={`${selectedFile.artifact.classroomUrl}${selectedFile.artifact.classroomUrl.includes('?') ? '&' : '?'}embedded=course-workspace`}
                className="h-full w-full rounded-xl border bg-white shadow-sm"
              />
            ) : selectedFile?.artifact ? (
              <iframe
                title={selectedFile.title}
                srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px/1.75 system-ui;color:#172033;max-width:960px;margin:0 auto;padding:42px}h1,h2,h3{color:#101828}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}</style></head><body>${selectedFile.artifact.htmlContent || markdownToArtifactHtml(`# ${selectedFile.artifact.title}\n\n${selectedFile.artifact.content}`)}</body></html>`}
                className="h-full w-full rounded-xl border bg-white shadow-sm"
              />
            ) : selectedFile?.material ? (
              <div className="flex h-full items-center justify-center rounded-xl border bg-white p-8 shadow-sm">
                <div className="w-full max-w-xl rounded-3xl border border-[#B00055]/15 bg-gradient-to-br from-white to-[#fff6fa] p-8 shadow-[0_20px_55px_-35px_rgba(176,0,85,.45)]">
                  <div className="mb-5 grid size-14 place-items-center rounded-2xl bg-[#B00055]/10 text-[#B00055]">
                    <Presentation className="size-7" />
                  </div>
                  <p className="text-xs font-medium uppercase tracking-[.18em] text-[#B00055]">
                    课程源材料
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-900">
                    {selectedFile.material.name}
                  </h2>
                  <div className="mt-5 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="rounded-full bg-slate-100 px-3 py-1.5">
                      {selectedFile.material.pageCount ?? 0} 页
                    </span>
                    <span className="rounded-full bg-emerald-50 px-3 py-1.5 text-emerald-700">
                      {
                        {
                          ready: '已完成解析',
                          uploaded: '已上传，待解析',
                          parsing: '正在解析',
                          'pending-review': '待审核',
                          failed: '解析失败',
                        }[selectedFile.material.status]
                      }
                    </span>
                  </div>
                  <p className="mt-5 text-sm leading-7 text-slate-600">
                    该文件已归档到课程资料，知识抽取、课件生成和备课智能体可继续引用此资料。
                  </p>
                  <Button className="mt-7 bg-[#B00055] hover:bg-[#8F0046]" asChild>
                    <a
                      href={`/api/course-space/${course.id}/materials/${selectedFile.material.id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开或下载原始文件
                      <ExternalLink className="ml-2 size-4" />
                    </a>
                  </Button>
                </div>
              </div>
            ) : selectedFile?.courseFile &&
              ['lesson-objectives', 'knowledge-points'].includes(selectedFile.courseFile.type) ? (
              <div className="flex h-full flex-col rounded-xl border bg-white p-5 shadow-sm">
                <h2 className="text-lg font-semibold">{selectedFile.title}</h2>
                <p className="my-3 text-xs text-slate-500">
                  审核顺序：课程目标 → 课程知识点 →
                  课件。可修改下方内容，保存草稿或审核通过后继续下一项。
                </p>
                <textarea
                  aria-label="编辑课程目标或知识点"
                  value={reviewContent}
                  onChange={(event) => setReviewContent(event.target.value)}
                  readOnly={Boolean(selectedFile.courseFile.classPublicationId)}
                  className="min-h-0 flex-1 resize-none rounded-lg border p-4 font-mono text-sm leading-7 outline-none focus:border-[#B00055]"
                />
              </div>
            ) : selectedFile?.courseFile ? (
              <iframe
                title={selectedFile.title}
                srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>
                  *{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#fff 0%,#fff9fc 100%);font:15px/1.75 system-ui,-apple-system,"Segoe UI",sans-serif;color:#344054}
                  main{max-width:980px;margin:0 auto;padding:42px 48px 64px}h1{margin:0 0 28px;font-size:30px;line-height:1.25;color:#101828;letter-spacing:-.02em}
                  h1:after{content:"";display:block;width:44px;height:4px;margin-top:14px;border-radius:999px;background:#B00055}
                  h2,h3{margin:30px 0 12px;color:#8F0046}h3{font-size:17px;padding-left:12px;border-left:3px solid #d678a5}
                  p{margin:10px 0;color:#475467}ul,ol{display:grid;gap:10px;margin:12px 0 24px;padding:0;list-style:none;counter-reset:item}
                  li{position:relative;padding:13px 18px 13px 46px;border:1px solid #f1d8e5;border-radius:14px;background:#fff;box-shadow:0 5px 18px rgba(79,20,49,.045)}
                  ul li:before{content:"";position:absolute;left:20px;top:22px;width:8px;height:8px;border-radius:50%;background:#B00055;box-shadow:0 0 0 5px #faeaf2}
                  ol li{counter-increment:item}ol li:before{content:counter(item);position:absolute;left:14px;top:12px;display:grid;place-items:center;width:24px;height:24px;border-radius:8px;background:#faeaf2;color:#9f004d;font-size:12px;font-weight:700}
                  strong{color:#101828}.source-citation{display:inline-flex;margin-left:4px;padding:1px 7px;border-radius:999px;background:#fff0f6;color:#9f004d;font-size:11px;white-space:nowrap}
                  .empty{margin-top:28px;padding:24px;border:1px dashed #d0d5dd;border-radius:16px;background:#f8fafc}
                  @media(max-width:700px){main{padding:28px 22px}li{padding-right:14px}}
                </style></head><body><main>${selectedFile.courseFile.content ? markdownToArtifactHtml(`# ${selectedFile.courseFile.title}\n\n${selectedFile.courseFile.content}`) : `${markdownToArtifactHtml(`# ${selectedFile.courseFile.title}`)}<div class="empty"><strong>文件已创建</strong><p>当前内容为空，可由备课工作智能体结合课程材料与知识图谱继续完善。</p></div>`}</main></body></html>`}
                className="h-full w-full rounded-xl border bg-white shadow-sm"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed bg-white text-sm text-slate-400">
                <Presentation className="mb-3 size-9 opacity-40" />
                <p>{folderView === 'AI课件' ? '当前文件夹还没有课件' : `暂无${folderView}`}</p>
                <p className="mt-1 text-xs">
                  {folderView === '课程资料'
                    ? '上一页上传的资料会自动保存在这里'
                    : folderView === '课程大纲'
                      ? '生成的课程大纲将保存在这里'
                      : '可通过课程操作入口启动标准课件生成流程'}
                </p>
              </div>
            )}
          </div>
        </section>
      </div>
      {publicationTarget && (
        <ResourcePublicationDialog
          key={publicationTarget.id}
          course={course}
          target={publicationTarget}
          onClose={() => setPublicationTarget(undefined)}
          onPublished={async () => {
            await onRefresh();
            setTreeMessage('文件已按确认的周次与课时归档并发布。');
          }}
        />
      )}
      {sourceEditId && course.materials.some((material) => material.id === sourceEditId) && (
        <SourceFileEditor
          courseId={course.id}
          material={course.materials.find((material) => material.id === sourceEditId)!}
          onClose={() => setSourceEditId('')}
          onReplaced={async (material) => {
            await onRefresh();
            setSelectedFileId(material.id);
            setTreeMessage('源文件已替换，课时归属和置顶已保留。请重新解析与审核新文件。');
          }}
        />
      )}
      {newFolder &&
        createPortal(
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !savingStructure) setNewFolder(undefined);
            }}
          >
            <form
              role="dialog"
              aria-modal="true"
              aria-label={newFolder.kind === 'module' ? '创建文件夹' : '创建子文件夹'}
              className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl"
              onSubmit={(event) => {
                event.preventDefault();
                const title = newFolderTitle.trim();
                if (!title || savingStructure) return;
                if (newFolder.kind === 'courseware') void addCoursewareFolder(title);
                else if (newFolder.kind === 'module') void addModule(title);
                else if (newFolder.moduleId) void addLesson(newFolder.moduleId, title);
              }}
            >
              <h3 className="text-base font-semibold text-slate-900">
                {newFolder.kind === 'module' ? '创建文件夹' : '创建子文件夹'}
              </h3>
              <input
                autoFocus
                value={newFolderTitle}
                onChange={(event) => setNewFolderTitle(event.target.value)}
                maxLength={100}
                placeholder={
                  newFolder.kind === 'module' ? '例如：习题、参考文献、教学反思' : '例如：第1周'
                }
                className="mt-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-[#B00055]"
              />
              {treeMessage && (
                <p className="mt-2 text-xs text-rose-600" role="alert">
                  {treeMessage}
                </p>
              )}
              <div className="mt-5 flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={savingStructure}
                  onClick={() => setNewFolder(undefined)}
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={!newFolderTitle.trim() || savingStructure}
                  className="bg-[#B00055] hover:bg-[#8F0046]"
                >
                  {savingStructure ? '创建中…' : '创建'}
                </Button>
              </div>
            </form>
          </div>,
          document.body,
        )}
    </div>
  );
}
