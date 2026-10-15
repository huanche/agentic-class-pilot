'use client';

import { useId, useState } from 'react';
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
  courseActive,
  onChange,
  onDeleted,
  course,
  onMoved,
}: {
  courseId: string;
  kind: 'artifacts' | 'materials' | 'lesson-files';
  id: string;
  title: string;
  published: boolean;
  courseActive: boolean;
  onChange: () => void | Promise<void>;
  onDeleted?: () => void | Promise<void>;
  course?: CourseSpace;
  onMoved?: (lessonId: string) => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pendingAction, setPendingAction] = useState<'delete' | 'publication' | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [targetLessonId, setTargetLessonId] = useState('');
  const targetSelectId = useId();
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
      ? '删除后将从课程和班级资料中移除，此操作无法撤销。'
      : published
        ? '取消后学生将无法继续打开此资源，教师仍可编辑并重新发布。'
        : '发布后本课程学生可见。';
  const change = async (remove: boolean) => {
    const action = remove ? '删除' : published ? '取消发布' : '发布到班级';
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        `/api/course-space/${encodeURIComponent(courseId)}/${kind}/${encodeURIComponent(id)}`,
        {
          method: remove ? 'DELETE' : 'PATCH',
          headers: { 'content-type': 'application/json' },
          ...(!remove
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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {course && (
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
        disabled={busy || (!published && !courseActive)}
        onClick={() => setPendingAction('publication')}
      >
        {busy ? '正在处理…' : published ? '取消发布' : courseActive ? '发布到班级' : '请先发布课程'}
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
      {error && !moveOpen && (
        <span role="alert" className="text-xs text-destructive">
          {error}
        </span>
      )}
      <AlertDialog
        open={pendingAction !== null}
        onOpenChange={(open) => {
          if (!open) setPendingAction(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {action}“{title}”？
            </AlertDialogTitle>
            <AlertDialogDescription>{consequence}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>保留当前状态</AlertDialogCancel>
            <AlertDialogAction onClick={() => void change(pendingAction === 'delete')}>
              确认{action}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={moveOpen}
        onOpenChange={(open) => {
          if (!busy) setMoveOpen(open);
        }}
      >
        <DialogContent className="max-w-lg" showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>移动“{title}”</DialogTitle>
            <DialogDescription>选择本课程中的目标课时。移动后发布状态保持不变。</DialogDescription>
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
