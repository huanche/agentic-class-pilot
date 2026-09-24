'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileText,
  Folder,
  History,
  GripVertical,
  Plus,
  Presentation,
  Sparkles,
  Trash2,
  Upload,
  Radio,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
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
type FolderMenu =
  | { kind: 'module'; id: string; title: string; x: number; y: number }
  | { kind: 'lesson'; id: string; title: string; x: number; y: number };
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
}: {
  course: CourseSpace;
  artifacts: CourseArtifactRecord[];
  onGenerate: (type: CourseArtifactType, scope?: CourseArtifactJob['scope']) => void;
  onCourseChange: (course: CourseSpace) => Promise<void>;
  onRefresh: () => Promise<void>;
  onScopeChange?: (scope: CourseArtifactJob['scope']) => void;
  showOriginBadges?: boolean;
  height?: number;
}) {
  const firstLesson = course.modules.flatMap((item) => item.lessons)[0];
  const initialArtifact = [...artifacts].sort(
    (a, b) => artifactPriority(b) - artifactPriority(a) || b.updatedAt - a.updatedAt,
  )[0];
  const [scope, setScope] = useState<Scope>(
    initialArtifact?.scope ??
      (firstLesson ? { type: 'lesson', lessonId: firstLesson.id } : { type: 'course' }),
  );
  const [expanded, setExpanded] = useState(() => new Set(course.modules.map((item) => item.id)));
  const [expandedLessons, setExpandedLessons] = useState(() => new Set<string>());
  const [courseFilesExpanded, setCourseFilesExpanded] = useState(true);
  const [selectedFileId, setSelectedFileId] = useState('');
  const [savingStructure, setSavingStructure] = useState(false);
  const [treeMessage, setTreeMessage] = useState('');
  const [folderMenu, setFolderMenu] = useState<FolderMenu>();
  const [dropTargetId, setDropTargetId] = useState('');
  const initializedFromArtifacts = useRef(false);
  const explorerRef = useRef<HTMLDivElement>(null);
  const [treeWidth, setTreeWidth] = useState(220);
  const [activating, setActivating] = useState(false);

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
    if (!folderMenu) return;
    const close = () => setFolderMenu(undefined);
    window.addEventListener('click', close);
    window.addEventListener('blur', close);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('blur', close);
    };
  }, [folderMenu]);
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
        : files[0];
  const selectScope = (next: Scope) => {
    setScope(next);
    setSelectedFileId('');
    onScopeChange?.(next);
  };
  const publishFileToClass = async (
    target?: Pick<BrowserFile, 'artifact' | 'material' | 'courseFile'>,
  ) => {
    const targetFile = target ?? selectedFile;
    if (!targetFile?.artifact && !targetFile?.material && !targetFile?.courseFile) return;
    const publicationId =
      targetFile.artifact?.classPublicationId ??
      targetFile.material?.classPublicationId ??
      targetFile.courseFile?.classPublicationId;
    if (publicationId) {
      setTreeMessage(`该资料已发布到班级，唯一标志：${publicationId}。发布后不可撤回。`);
      return;
    }
    if (!window.confirm('确认将该文件发布到 Class 通道吗？发布后不可撤回。')) return;
    const url = targetFile.artifact
      ? `/api/course-space/${course.id}/artifacts/${targetFile.artifact.id}`
      : targetFile.material
        ? `/api/course-space/${course.id}/materials/${targetFile.material.id}`
        : `/api/course-space/${course.id}/lesson-files/${targetFile.courseFile!.id}`;
    setActivating(true);
    setTreeMessage('');
    try {
      const response = await fetch(url, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(
          targetFile.artifact
            ? { action: 'activate' }
            : targetFile.material
              ? { active: true }
              : { action: 'publish' },
        ),
      });
      const result = (await response.json().catch(() => undefined)) as
        | {
            error?: string;
            artifact?: { classPublicationId?: string };
            material?: { classPublicationId?: string };
            file?: { classPublicationId?: string };
          }
        | undefined;
      if (!response.ok) throw new Error(result?.error || '班级资料发布失败');
      await onRefresh();
      const issuedId =
        result?.artifact?.classPublicationId ??
        result?.material?.classPublicationId ??
        result?.file?.classPublicationId;
      setTreeMessage(`已发布到班级${issuedId ? `，唯一标志：${issuedId}` : ''}。发布后不可撤回。`);
    } catch (error) {
      setTreeMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setActivating(false);
    }
  };
  const addModule = async () => {
    const title = window.prompt('请输入新模块名称');
    if (!title?.trim()) return;
    const now = Date.now();
    const moduleId = nanoid(10);
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
  };
  const addLesson = async (moduleId: string) => {
    const title = window.prompt('请输入课时文件夹名称，例如“第1周”');
    if (!title?.trim()) return;
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
      setTreeMessage(`已创建文件夹“${title.trim()}”。`);
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
  const deleteFolder = async (menu: FolderMenu) => {
    const isModule = menu.kind === 'module';
    const courseModule = isModule ? course.modules.find((item) => item.id === menu.id) : undefined;
    const lesson = !isModule
      ? course.modules.flatMap((item) => item.lessons).find((item) => item.id === menu.id)
      : undefined;
    const fileCount = courseModule
      ? courseModule.lessons.reduce(
          (count, item) => count + (item.files?.length ?? 0) + item.materialIds.length,
          0,
        )
      : (lesson?.files?.length ?? 0) + (lesson?.materialIds.length ?? 0);
    const warning = fileCount
      ? `\n\n其中包含 ${fileCount} 个课程文件；教学产物也会一并删除，原始材料库记录仍保留。`
      : '';
    if (!window.confirm(`确认删除${isModule ? '模块' : '课时文件夹'}“${menu.title}”吗？${warning}`))
      return;
    const succeeded = await runTreeAction({
      action: isModule ? 'delete-module' : 'delete-lesson',
      [isModule ? 'moduleId' : 'lessonId']: menu.id,
    });
    if (succeeded) {
      selectScope({ type: 'course' });
      setTreeMessage(`已删除“${menu.title}”。`);
    }
  };
  const startDragging = (event: React.DragEvent<HTMLElement>, item: DragItem) => {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/x-mentra-course-item', JSON.stringify(item));
  };
  const dropIntoLesson = async (event: React.DragEvent<HTMLElement>, lessonId: string) => {
    event.preventDefault();
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
        setExpandedLessons((items) => new Set(items).add(lessonId));
        setTreeMessage('文件已移动到目标课时文件夹。');
      }
    } catch {
      setTreeMessage('拖拽数据无效，请重新操作。');
    }
  };

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
          {showOriginBadges && (
            <div className="mb-3 rounded-xl border border-slate-200 bg-white px-2.5 py-2">
              <p className="mb-1.5 text-[10px] font-medium text-slate-500">材料来源</p>
              <div className="flex flex-wrap items-center gap-1.5">
                <OriginBadge origin="teacher" />
                <OriginBadge origin="agent" />
                <ClassPublicationBadge publicationId="CLS-…" />
                <ClassPublicationBadge />
              </div>
            </div>
          )}
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
              课程级文件
            </button>
            <button
              title="添加模块"
              aria-label="添加模块"
              onClick={() => void addModule()}
              className="grid size-7 shrink-0 place-items-center rounded-lg border bg-white text-[#B00055] hover:bg-[#B00055]/5"
            >
              <Plus className="size-3.5" />
            </button>
          </div>
          {courseFilesExpanded && (
            <div className="mb-2 ml-6 max-h-56 space-y-0.5 overflow-y-auto border-l pl-2">
              <div className="flex items-center gap-2 px-2 py-1.5 text-[10px] font-medium text-slate-400">
                <History className="size-3" />
                历史教学产物 · {artifacts.length}
              </div>
              {artifacts.map((artifact) => (
                <button
                  key={artifact.id}
                  draggable
                  onDragStart={(event) =>
                    startDragging(event, { kind: 'artifact', id: artifact.id })
                  }
                  title={artifact.title}
                  onClick={() => {
                    setScope(artifact.scope);
                    setSelectedFileId(artifact.id);
                  }}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === artifact.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-600 hover:bg-slate-100'}`}
                >
                  {artifact.classroomUrl ? (
                    <Presentation className="size-3.5 shrink-0 text-[#B00055]" />
                  ) : (
                    <FileText className="size-3.5 shrink-0 text-blue-500" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{artifact.title}</span>
                  {showOriginBadges && (
                    <span className="ml-auto flex shrink-0 items-center gap-1">
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
                </button>
              ))}
            </div>
          )}
          <div className="space-y-1">
            {treeMessage && (
              <div className="mb-2 rounded-lg border border-[#B00055]/15 bg-white px-2.5 py-2 text-[11px] leading-4 text-slate-600">
                {treeMessage}
              </div>
            )}
            {course.modules.map((module) => (
              <div key={module.id}>
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
                  <button
                    onClick={() => selectScope({ type: 'module', moduleId: module.id })}
                    onContextMenu={(event) => {
                      event.preventDefault();
                      setFolderMenu({
                        kind: 'module',
                        id: module.id,
                        title: module.title,
                        x: event.clientX,
                        y: event.clientY,
                      });
                    }}
                    className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs ${scope.type === 'module' && scope.moduleId === module.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'hover:bg-slate-100'}`}
                  >
                    <Folder className="size-4 shrink-0 text-amber-500" />
                    <span className="truncate">{module.title}</span>
                  </button>
                  <button
                    title={`在“${module.title}”下添加课时文件夹`}
                    aria-label={`在“${module.title}”下添加课时文件夹`}
                    onClick={() => void addLesson(module.id)}
                    disabled={savingStructure}
                    className="mr-1 grid size-6 shrink-0 place-items-center rounded-md text-slate-400 opacity-60 hover:bg-[#B00055]/10 hover:text-[#B00055] group-hover/module:opacity-100"
                  >
                    <Plus className="size-3.5" />
                  </button>
                </div>
                {expanded.has(module.id) && (
                  <div className="ml-6 border-l pl-2">
                    {[...module.lessons]
                      .sort((a, b) => a.order - b.order)
                      .map((lesson) => {
                        const artifactFiles = artifacts.filter(
                          (artifact) =>
                            artifact.scope.type === 'lesson' &&
                            artifact.scope.lessonId === lesson.id,
                        );
                        const structureFiles = lesson.files ?? [];
                        const lessonMaterials = course.materials.filter((material) =>
                          lesson.materialIds.includes(material.id),
                        );
                        const fileCount =
                          artifactFiles.length + structureFiles.length + lessonMaterials.length;
                        const isExpanded = expandedLessons.has(lesson.id);
                        return (
                          <div key={lesson.id}>
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
                              <button
                                onClick={() => {
                                  selectScope({ type: 'lesson', lessonId: lesson.id });
                                  setExpandedLessons((items) => new Set(items).add(lesson.id));
                                }}
                                onContextMenu={(event) => {
                                  event.preventDefault();
                                  setFolderMenu({
                                    kind: 'lesson',
                                    id: lesson.id,
                                    title: lesson.title,
                                    x: event.clientX,
                                    y: event.clientY,
                                  });
                                }}
                                onDragOver={(event) => {
                                  event.preventDefault();
                                  event.dataTransfer.dropEffect = 'move';
                                  setDropTargetId(lesson.id);
                                }}
                                onDragLeave={() => setDropTargetId('')}
                                onDrop={(event) => void dropIntoLesson(event, lesson.id)}
                                className={`my-0.5 flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-2 text-left text-xs ${dropTargetId === lesson.id ? 'ring-2 ring-[#B00055]/40 bg-[#B00055]/10' : ''} ${scope.type === 'lesson' && scope.lessonId === lesson.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-600 hover:bg-slate-100'}`}
                              >
                                <Folder className="size-3.5 shrink-0 text-[#B00055]" />
                                <span className="truncate">{lesson.title}</span>
                                {fileCount > 0 && (
                                  <span className="ml-auto text-[10px] text-slate-400">
                                    {fileCount}
                                  </span>
                                )}
                              </button>
                            </div>
                            {isExpanded && fileCount > 0 && (
                              <div className="ml-5 border-l pl-2">
                                {lessonMaterials.map((material) => (
                                  <button
                                    key={material.id}
                                    draggable
                                    onDragStart={(event) =>
                                      startDragging(event, { kind: 'material', id: material.id })
                                    }
                                    title={material.name}
                                    onClick={() => {
                                      setScope({ type: 'lesson', lessonId: lesson.id });
                                      setSelectedFileId(material.id);
                                    }}
                                    className={`my-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === material.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
                                  >
                                    <Presentation className="size-3.5 shrink-0 text-orange-500" />
                                    <span className="min-w-0 flex-1 truncate">{material.name}</span>
                                    {showOriginBadges && (
                                      <span className="ml-auto flex shrink-0 items-center gap-1">
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
                                  </button>
                                ))}
                                {structureFiles.map((file) => (
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
                                    className={`my-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === file.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
                                  >
                                    <FileText className="size-3.5 shrink-0 text-blue-500" />
                                    <span className="min-w-0 flex-1 truncate">{file.title}</span>
                                    {showOriginBadges && (
                                      <span className="ml-auto flex shrink-0 items-center gap-1">
                                        <OriginBadge origin="agent" />
                                        <ClassPublicationBadge
                                          publicationId={
                                            course.status === 'active'
                                              ? file.classPublicationId
                                              : undefined
                                          }
                                          onPublish={
                                            course.status === 'active'
                                              ? () => void publishFileToClass({ courseFile: file })
                                              : undefined
                                          }
                                        />
                                      </span>
                                    )}
                                  </button>
                                ))}
                                {artifactFiles.map((artifact) => (
                                  <button
                                    key={artifact.id}
                                    draggable
                                    onDragStart={(event) =>
                                      startDragging(event, { kind: 'artifact', id: artifact.id })
                                    }
                                    title={artifact.title}
                                    onClick={() => {
                                      setScope({ type: 'lesson', lessonId: lesson.id });
                                      setSelectedFileId(artifact.id);
                                    }}
                                    className={`my-0.5 flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11px] ${selectedFileId === artifact.id ? 'bg-[#B00055]/10 font-medium text-[#8F0046]' : 'text-slate-500 hover:bg-slate-100'}`}
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
                                      <span className="ml-auto flex shrink-0 items-center gap-1">
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
                                  </button>
                                ))}
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
          {folderMenu && (
            <div
              role="menu"
              className="fixed z-50 min-w-36 rounded-xl border bg-white p-1.5 shadow-xl"
              style={{ left: folderMenu.x, top: folderMenu.y }}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                role="menuitem"
                disabled={savingStructure}
                onClick={() => {
                  const menu = folderMenu;
                  setFolderMenu(undefined);
                  void deleteFolder(menu);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                <Trash2 className="size-3.5" />
                删除
              </button>
            </div>
          )}
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
          <div className="flex h-11 shrink-0 items-center justify-between border-b bg-white px-4">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium text-slate-700">
                {selectedFile?.title || '课程文件'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {(selectedFile?.artifact || selectedFile?.material) && (
                <Button
                  size="sm"
                  variant={
                    selectedFile.artifact?.classPublicationId ||
                    selectedFile.material?.classPublicationId
                      ? 'default'
                      : 'outline'
                  }
                  disabled={
                    activating ||
                    course.status !== 'active' ||
                    Boolean(
                      selectedFile.artifact?.classPublicationId ||
                      selectedFile.material?.classPublicationId,
                    )
                  }
                  onClick={() => void publishFileToClass()}
                  className={
                    selectedFile.artifact?.classPublicationId ||
                    selectedFile.material?.classPublicationId
                      ? 'bg-emerald-600 disabled:opacity-100'
                      : course.status === 'active'
                        ? 'border-[#B00055] bg-[#B00055] text-white hover:bg-[#8F0046] hover:text-white'
                        : ''
                  }
                >
                  <Radio className="mr-1 size-3.5" />
                  {selectedFile.artifact?.classPublicationId ||
                  selectedFile.material?.classPublicationId
                    ? `已发布 · ${(selectedFile.artifact?.classPublicationId ??
                        selectedFile.material?.classPublicationId)!.slice(-6)}`
                    : course.status !== 'active'
                      ? '请先发布课程'
                      : '发布到班级'}
                </Button>
              )}
              {selectedFile?.artifact?.classroomUrl && (
                <Button size="sm" variant="outline" asChild>
                  <a href={selectedFile.artifact.classroomUrl} target="_blank" rel="noreferrer">
                    全屏打开
                    <ExternalLink className="ml-1 size-3.5" />
                  </a>
                </Button>
              )}
            </div>
          </div>
          <div className="min-h-0 flex-1 p-2">
            {selectedFile?.artifact?.classroomUrl ? (
              <iframe
                title={selectedFile.title}
                src={`${selectedFile.artifact.classroomUrl}?embedded=course-workspace`}
                className="h-full w-full rounded-xl border bg-white shadow-sm"
              />
            ) : selectedFile?.artifact ? (
              <iframe
                title={selectedFile.title}
                srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px/1.75 system-ui;color:#172033;max-width:960px;margin:0 auto;padding:42px}h1,h2,h3{color:#101828}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}</style></head><body>${selectedFile.artifact.htmlContent || `<h1>${selectedFile.artifact.title}</h1><pre>${selectedFile.artifact.content}</pre>`}</body></html>`}
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
                      {selectedFile.material.status === 'ready'
                        ? '已完成解析'
                        : selectedFile.material.status}
                    </span>
                  </div>
                  <p className="mt-5 text-sm leading-7 text-slate-600">
                    该 PPT 已归档到当前周课时文件夹，知识抽取、课件生成和备课智能体仍通过材料 ID
                    保留来源引用。
                  </p>
                  <Button className="mt-7 bg-[#B00055] hover:bg-[#8F0046]" asChild>
                    <a
                      href={`/api/course-space/${course.id}/materials/${selectedFile.material.id}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开或下载原始 PPT
                      <ExternalLink className="ml-2 size-4" />
                    </a>
                  </Button>
                </div>
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
                </style></head><body><main>${selectedFile.courseFile.content ? markdownToArtifactHtml(`# ${selectedFile.courseFile.title}\n\n${selectedFile.courseFile.content}`) : `<h1>${selectedFile.courseFile.title}</h1><div class="empty"><strong>文件已创建</strong><p>当前内容为空，可由备课工作智能体结合课程材料与知识图谱继续完善。</p></div>`}</main></body></html>`}
                className="h-full w-full rounded-xl border bg-white shadow-sm"
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed bg-white text-sm text-slate-400">
                <Presentation className="mb-3 size-9 opacity-40" />
                <p>当前范围还没有课件</p>
                <p className="mt-1 text-xs">可通过课程操作入口启动标准课件生成流程</p>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
