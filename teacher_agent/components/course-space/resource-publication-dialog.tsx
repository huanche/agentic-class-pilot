'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import type { CourseSpace, CoursePublicationPlacement } from '@/lib/course-space/types';
export type PublicationTarget = {
  kind: 'artifact' | 'material' | 'course-file';
  id: string;
  title: string;
  lessonId?: string;
  resourceType: CoursePublicationPlacement['resourceType'];
  storageType: string;
};
const suggestedWeek = (title?: string) => Number(title?.match(/第\s*(\d+)\s*周/u)?.[1]) || 1;
const labels = {
  courseware: 'AI课件',
  objectives: '课程目标',
  'knowledge-points': '课程知识点',
  outline: '课程大纲',
  exercise: '习题',
  material: '教学资料',
};
export function ResourcePublicationDialog({
  course,
  target,
  onClose,
  onPublished,
}: {
  course: CourseSpace;
  target: PublicationTarget;
  onClose: () => void;
  onPublished: () => Promise<void> | void;
}) {
  const lessons = course.modules.flatMap((module) => module.lessons);
  const initial = lessons.find((lesson) => lesson.id === target.lessonId);
  const [lessonId, setLessonId] = useState(initial?.id ?? '');
  const [week, setWeek] = useState(initial?.week ?? suggestedWeek(initial?.title));
  const [lessonNumber, setLessonNumber] = useState(initial?.lessonNumber ?? 1);
  const [hours, setHours] = useState(initial?.teachingHours ?? 1);
  const [newTitle, setNewTitle] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectLesson = (id: string) => {
    setLessonId(id);
    setConfirmed(false);
    const lesson = lessons.find((item) => item.id === id);
    setWeek(lesson?.week ?? suggestedWeek(lesson?.title));
    setLessonNumber(lesson?.lessonNumber ?? 1);
    setHours(lesson?.teachingHours ?? 1);
  };
  const publish = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/${course.id}/publications`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          kind: target.kind,
          id: target.id,
          placement: {
            lessonId,
            newLessonTitle: lessonId ? undefined : newTitle,
            week,
            lessonNumber,
            teachingHours: hours,
            resourceType: target.resourceType,
          },
        }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '发布失败');
      await onPublished();
      onClose();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };
  const inputClass = 'mt-1 w-full rounded-lg border px-3 py-2 text-sm';
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>确认文件归属并发布</DialogTitle>
          <DialogDescription>
            请明确这份文件属于哪次课。学生将按此课时读取资料和播放课件，不能使用其他课时的课件替代。
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg bg-slate-50 p-3 text-sm">
          <p className="font-medium">{target.title}</p>
          <p className="mt-1 text-xs text-slate-500">课程：{course.title}</p>
          <p className="mt-1 text-xs text-slate-500">
            存储类型：{labels[target.resourceType]} · {target.storageType}
          </p>
        </div>
        <label className="text-sm">
          所属课时
          <select
            className={inputClass}
            value={lessonId}
            onChange={(event) => selectLesson(event.target.value)}
            disabled={busy}
          >
            <option value="">＋ 新建课时并归档</option>
            {lessons.map((lesson) => (
              <option key={lesson.id} value={lesson.id}>
                {lesson.title}
                {lesson.week
                  ? `（第${lesson.week}周，第${lesson.lessonNumber}次课）`
                  : '（待确认周次）'}
              </option>
            ))}
          </select>
        </label>
        {!lessonId && (
          <label className="text-sm">
            新课时名称
            <input
              className={inputClass}
              value={newTitle}
              maxLength={100}
              onChange={(event) => {
                setNewTitle(event.target.value);
                setConfirmed(false);
              }}
              placeholder="例如：第2周第1次课 · 电路交换"
              disabled={busy}
            />
            <span className="mt-1 block text-xs text-slate-500">
              还没有课时？填写名称后，系统会先创建课时，再将本文件归入该课时。
            </span>
          </label>
        )}
        <div className="grid grid-cols-3 gap-3">
          <label className="text-sm">
            周次
            <input
              type="number"
              min={1}
              max={100}
              required
              className={inputClass}
              value={week}
              disabled={busy}
              onChange={(event) => {
                setWeek(Number(event.target.value));
                setConfirmed(false);
              }}
            />
          </label>
          <label className="text-sm">
            该周第几次课
            <input
              type="number"
              min={1}
              max={1000}
              required
              className={inputClass}
              value={lessonNumber}
              disabled={busy}
              onChange={(event) => {
                setLessonNumber(Number(event.target.value));
                setConfirmed(false);
              }}
            />
          </label>
          <label className="text-sm">
            课时数
            <input
              type="number"
              min={0.5}
              max={24}
              step={0.5}
              required
              className={inputClass}
              value={hours}
              disabled={busy}
              onChange={(event) => {
                setHours(Number(event.target.value));
                setConfirmed(false);
              }}
            />
          </label>
        </div>
        <p className="rounded-lg bg-amber-50 p-3 text-xs leading-5 text-amber-800">
          请区分周次、课次和课时数。例如第2周第1次课占2课时，应填写“2 / 1 /
          2”。同一次课的目标、知识点和课件应选择同一个课时。发布后归属不能直接更改。
        </p>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={confirmed}
            disabled={busy}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            我已核对资料类型、第{week}周第{lessonNumber}次课（{hours}
            课时），确认学生应在此课时查看本文件。
          </span>
        </label>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={
              busy ||
              !confirmed ||
              (!lessonId && !newTitle.trim()) ||
              week < 1 ||
              lessonNumber < 1 ||
              hours <= 0
            }
            onClick={() => void publish()}
          >
            {busy ? '正在归档并发布…' : '确认归属并发布'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
