'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
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
}: {
  courseId: string;
  kind: 'artifacts' | 'materials' | 'lesson-files';
  id: string;
  title: string;
  published: boolean;
  courseActive: boolean;
  onChange: () => void | Promise<void>;
  onDeleted?: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [pendingAction, setPendingAction] = useState<'delete' | 'publication' | null>(null);
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
      {error && (
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
    </div>
  );
}
