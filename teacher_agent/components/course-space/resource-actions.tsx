'use client';

import { useId, useState, type ReactNode } from 'react';
import { FolderInput, FolderOpen, Pencil, Pin, PinOff, Send, Trash2, Undo2 } from 'lucide-react';
import { WorkspaceItemMenu, type WorkspaceMenuAction } from './workspace-item-menu';
import { Button } from '@/components/ui/button';
import type { CourseSpace } from '@/lib/course-space/types';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

/** One publication lifecycle for generated resources, source materials and lesson files. */
export function ResourceActions({
  courseId,
  kind,
  id,
  title,
  published,
  publicationLabel = '发布到班级',
  onChange,
  onDeleted,
  course,
  onMoved,
  onPublish,
  presentation = 'buttons',
  pinned = false,
  children,
  onEdit,
  onReveal,
  extraActions = [],
}: {
  courseId: string;
  kind: 'artifacts' | 'materials' | 'lesson-files' | 'modules' | 'lessons';
  id: string;
  title: string;
  published: boolean;
  publicationLabel?: string;
  onChange: () => void | Promise<void>;
  onDeleted?: () => void | Promise<void>;
  course?: CourseSpace;
  onMoved?: (lessonId: string) => void | Promise<void>;
  onPublish?: () => void;
  presentation?: 'buttons' | 'menu';
  pinned?: boolean;
  children?: ReactNode;
  onEdit?: () => void;
  onReveal?: () => void;
  extraActions?: WorkspaceMenuAction[];
}) {
  const isFolder = kind === 'modules' || kind === 'lessons';
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pendingAction, setPendingAction] = useState<'delete' | 'publication' | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [targetLessonId, setTargetLessonId] = useState('');
  const [renameOpen, setRenameOpen] = useState(false);
  const [newTitle, setNewTitle] = useState(title);
  const renameInputId = useId();
  const targetSelectId = useId();
  const updateMetadata = async (patch: { title?: string; pinned?: boolean }) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/${encodeURIComponent(courseId)}/management`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ kind, id, ...patch }),
      });
      const result = await response.json();
      if (!response.ok || result.success === false) throw new Error(result.error || '保存失败');
      await onChange();
      setRenameOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  const lessons =
    course?.modules.flatMap((module) =>
      module.lessons.map((lesson) => ({
        id: lesson.id,
        label: `${module.title} / ${lesson.title}`,
      })),
    ) ?? [];
  const move = async () => {
    if (!targetLessonId || busy) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/${encodeURIComponent(courseId)}/tree`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          action: 'move-item',
          itemKind:
            kind === 'artifacts' ? 'artifact' : kind === 'materials' ? 'material' : 'course-file',
          itemId: id,
          targetLessonId,
        }),
      });
      const result = await response.json();
      if (!response.ok || result.success === false) throw new Error(result.error || '移动失败');
      await onChange();
      await onMoved?.(targetLessonId);
      setMoveOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  const action = pendingAction === 'delete' ? '删除' : published ? '取消发布' : '发布到班级';
  const consequence =
    pendingAction === 'delete'
      ? isFolder
        ? '删除文件夹会同时移除其中的课时文件和生成产物，原始材料库记录保留。已有发布文件的目录不能删除。此操作无法撤销。'
        : '删除后将从课程和班级资料中移除，此操作无法撤销。'
      : published
        ? '取消后学生将无法继续打开此资源，教师仍可编辑并重新发布。'
        : '发布后本课程学生可见。';
  const change = async (remove: boolean) => {
    const action = remove ? '删除' : published ? '取消发布' : '发布到班级';
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        isFolder
          ? `/api/course-space/${encodeURIComponent(courseId)}/tree`
          : `/api/course-space/${encodeURIComponent(courseId)}/${kind}/${encodeURIComponent(id)}`,
        {
          method: isFolder ? 'POST' : remove ? 'DELETE' : 'PATCH',
          headers: { 'content-type': 'application/json' },
          ...(isFolder
            ? {
                body: JSON.stringify({
                  action: kind === 'modules' ? 'delete-module' : 'delete-lesson',
                  [kind === 'modules' ? 'moduleId' : 'lessonId']: id,
                }),
              }
            : !remove
              ? {
                  body: JSON.stringify(
                    kind === 'materials'
                      ? { active: !published }
                      : {
                          action:
                            kind === 'artifacts'
                              ? published
                                ? 'deactivate'
                                : 'activate'
                              : published
                                ? 'unpublish'
                                : 'publish',
                        },
                  ),
                }
              : {}),
        },
      );
      const result = await response.json();
      if (!response.ok || result.success === false)
        throw new Error(result.error || `${action}失败`);
      if (remove && onDeleted) await onDeleted();
      else await onChange();
      setPendingAction(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  const actions: WorkspaceMenuAction[] = [
    ...extraActions,
    {
      label: '重命名',
      icon: <Pencil />,
      disabled: busy,
      onSelect: () => {
        setNewTitle(title);
        setError('');
        setRenameOpen(true);
      },
    },
    {
      label: pinned ? '取消置顶' : '置顶',
      icon: pinned ? <PinOff /> : <Pin />,
      disabled: busy,
      onSelect: () => void updateMetadata({ pinned: !pinned }),
    },
    ...(onEdit
      ? [
          {
            label: published ? '编辑（请先取消发布）' : isFolder ? '编辑文件夹' : '编辑',
            icon: <Pencil />,
            onSelect: onEdit,
            movesFocus: true,
            disabled: busy || published,
          },
        ]
      : []),
    ...(onReveal
      ? [{ label: '打开文件位置', icon: <FolderOpen />, onSelect: onReveal, movesFocus: true }]
      : []),
    ...(!isFolder && course
      ? [
          {
            label: '移动到…',
            icon: <FolderInput />,
            disabled: busy,
            separator: true,
            onSelect: () => {
              setError('');
              setTargetLessonId('');
              setMoveOpen(true);
            },
          },
        ]
      : []),
    ...(!isFolder
      ? [
          {
            label: published ? '取消发布' : publicationLabel,
            icon: published ? <Undo2 /> : <Send />,
            disabled: busy || (!published && course?.status === 'archived'),
            onSelect: () => (published ? setPendingAction('publication') : onPublish?.()),
          },
        ]
      : []),
    {
      label: '删除',
      icon: <Trash2 />,
      destructive: true,
      separator: true,
      disabled: busy,
      onSelect: () => {
        setError('');
        setPendingAction('delete');
      },
    },
  ];
  return (
    <div className={children ? 'min-w-0 flex-1' : 'flex flex-wrap items-center gap-2'}>
      {presentation === 'menu' ? (
        <WorkspaceItemMenu title={title} pinned={pinned} actions={actions}>
          {children}
        </WorkspaceItemMenu>
      ) : (
        <>
          {course && !isFolder && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setError('');
                setTargetLessonId('');
                setMoveOpen(true);
              }}
            >
              移动
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={busy || (!published && course?.status === 'archived')}
            onClick={() => (published ? setPendingAction('publication') : onPublish?.())}
          >
            {busy ? '正在处理…' : published ? '取消发布' : publicationLabel}
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="text-destructive"
            disabled={busy}
            onClick={() => setPendingAction('delete')}
          >
            删除
          </Button>
        </>
      )}
      {error && !moveOpen && !renameOpen && !pendingAction && (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      )}
      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setPendingAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {action}“{title}”？
            </AlertDialogTitle>
            <AlertDialogDescription>{consequence}</AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>保留当前状态</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={(event) => {
                event.preventDefault();
                void change(pendingAction === 'delete');
              }}
            >
              {busy ? '正在处理…' : `确认${action}`}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={renameOpen}
        onOpenChange={(open) => {
          if (!busy) setRenameOpen(open);
        }}
      >
        <DialogContent className="max-w-md" showCloseButton={!busy}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (newTitle.trim()) void updateMetadata({ title: newTitle.trim() });
            }}
          >
            <DialogHeader>
              <DialogTitle>重命名{isFolder ? '文件夹' : '文件'}</DialogTitle>
              <DialogDescription>
                {kind === 'materials'
                  ? '名称会同步显示在课程目录中，原文件扩展名将保留。'
                  : '名称会同步显示在课程目录中。'}
              </DialogDescription>
            </DialogHeader>
            <label className="mt-4 block text-sm" htmlFor={renameInputId}>
              名称
            </label>
            <input
              id={renameInputId}
              autoFocus
              onFocus={(event) => {
                const extension =
                  kind === 'materials' ? newTitle.match(/\.[a-zA-Z0-9]{1,12}$/)?.[0] : undefined;
                event.target.setSelectionRange(
                  0,
                  extension ? newTitle.length - extension.length : newTitle.length,
                );
              }}
              value={newTitle}
              maxLength={180}
              disabled={busy}
              onChange={(event) => setNewTitle(event.target.value)}
              className="mt-2 w-full rounded-md border bg-background px-3 py-2 text-sm"
            />
            {error && (
              <p role="alert" className="mt-2 text-sm text-destructive">
                {error}
              </p>
            )}
            <DialogFooter className="mt-5">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => setRenameOpen(false)}
              >
                取消
              </Button>
              <Button type="submit" disabled={busy || !newTitle.trim()}>
                {busy ? '保存中…' : '保存名称'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={moveOpen}
        onOpenChange={(open) => {
          if (!busy) setMoveOpen(open);
        }}
      >
        <DialogContent className="max-w-lg" showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>移动“{title}”</DialogTitle>
            <DialogDescription>
              选择本课程中的目标课时。已发布文件会同步更新课时归属并保留发布状态；目标课时须已确认周次和课时数。
            </DialogDescription>
          </DialogHeader>
          {lessons.length ? (
            <div className="grid gap-2">
              <label htmlFor={targetSelectId}>目标课时</label>
              <select
                id={targetSelectId}
                className="w-full rounded-md border bg-background p-2"
                value={targetLessonId}
                disabled={busy}
                onChange={(event) => {
                  setTargetLessonId(event.target.value);
                  setError('');
                }}
              >
                <option value="">请选择课时</option>
                {lessons.map((lesson) => (
                  <option key={lesson.id} value={lesson.id}>
                    {lesson.label}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p>课程中还没有课时，请先创建课时文件夹。</p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setMoveOpen(false)}>
              取消
            </Button>
            <Button disabled={busy || !targetLessonId} onClick={() => void move()}>
              {busy ? '正在移动…' : '确认移动'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
