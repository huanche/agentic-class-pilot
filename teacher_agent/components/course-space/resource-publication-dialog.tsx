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
import type {
  CourseSpace,
  CourseLesson,
  CoursePublicationPlacement,
} from '@/lib/course-space/types';
export type PublicationTarget = {
  kind: 'artifact' | 'material' | 'course-file';
  id: string;
  title: string;
  lessonId?: string;
  resourceType: CoursePublicationPlacement['resourceType'];
  storageType: string;
};
function hasLessonPlacement(lesson?: CourseLesson) {
  return Boolean(
    lesson &&
    Number.isInteger(lesson.week) &&
    lesson.week! >= 1 &&
    lesson.week! <= 100 &&
    Number.isInteger(lesson.lessonNumber) &&
    lesson.lessonNumber! >= 1 &&
    lesson.lessonNumber! <= 1000 &&
    Number.isFinite(lesson.teachingHours) &&
    lesson.teachingHours! > 0 &&
    lesson.teachingHours! <= 24,
  );
}
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
  const lessonFields = (id?: string) => {
    const courseModule = course.modules.find((item) =>
      item.lessons.some((lesson) => lesson.id === id),
    );
    const lesson = courseModule?.lessons.find((item) => item.id === id);
    return {
      week: String(
        lesson?.week ??
          courseModule?.title.match(/第\s*(\d+)\s*周/u)?.[1] ??
          lesson?.title.match(/第\s*(\d+)\s*周/u)?.[1] ??
          '',
      ),
      lessonNumber: String(
        lesson?.lessonNumber ?? lesson?.title.match(/第\s*(\d+)\s*次课/u)?.[1] ?? '',
      ),
      hours: String(lesson?.teachingHours ?? course.curriculum?.teachingHoursPerLesson ?? ''),
    };
  };
  const initialFields = lessonFields(initial?.id);
  const [lessonId, setLessonId] = useState(initial?.id ?? '');
  const [week, setWeek] = useState(initialFields.week);
  const [lessonNumber, setLessonNumber] = useState(initialFields.lessonNumber);
  const [hours, setHours] = useState(initialFields.hours);
  const [newTitle, setNewTitle] = useState('');
  const [showDetails, setShowDetails] = useState(!hasLessonPlacement(initial));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const isCourseware = target.resourceType === 'courseware';
  const selectedLesson = lessons.find((lesson) => lesson.id === lessonId);
  const selectedModule = course.modules.find((module) =>
    module.lessons.some((lesson) => lesson.id === lessonId),
  );
  const location = [course.title, selectedModule?.title, selectedLesson?.title]
    .filter(Boolean)
    .join(' / ');
  const selectLesson = (id: string) => {
    setLessonId(id);
    setError('');
    const fields = lessonFields(id);
    setWeek(fields.week);
    setLessonNumber(fields.lessonNumber);
    setHours(fields.hours);
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
            week: Number(week),
            lessonNumber: Number(lessonNumber),
            teachingHours: Number(hours),
            resourceType: target.resourceType,
          },
        }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) {
        if (response.status === 400 || response.status === 409) setShowDetails(true);
        throw new Error(data.error || '发布失败');
      }
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
          <DialogTitle>{isCourseware ? '发布课件' : '发布资料'}</DialogTitle>
          <DialogDescription>
            发布后，本课程学生即可查看{isCourseware ? '和使用此课件' : '此资料'}。
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-xl border border-[#B00055]/10 bg-[#B00055]/[0.03] p-4 text-sm">
          <p className="font-medium">{target.title}</p>
          <p className="mt-3 text-xs text-slate-500">发布位置</p>
          <div className="mt-1 flex items-start justify-between gap-3">
            <p className="text-xs leading-5 text-slate-600">
              {selectedLesson ? location : '请选择所属课时'}
            </p>
            {selectedLesson && hasLessonPlacement(selectedLesson) && (
              <button
                type="button"
                className="shrink-0 text-xs text-[#B00055] hover:underline"
                disabled={busy}
                onClick={() => setShowDetails((open) => !open)}
              >
                {showDetails ? '完成' : '更改'}
              </button>
            )}
          </div>
        </div>
        {showDetails && (
          <div className="space-y-4">
            {!hasLessonPlacement(selectedLesson) && (
              <p className="text-xs text-slate-500">请补全课时归属，已有信息已自动带入。</p>
            )}
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
                    {
                      course.modules.find((module) =>
                        module.lessons.some((item) => item.id === lesson.id),
                      )?.title
                    }{' '}
                    / {lesson.title}
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
                    setError('');
                  }}
                  placeholder="例如：第2周第1次课 · 电路交换"
                  disabled={busy}
                />
                <span className="mt-1 block text-xs text-slate-500">
                  还没有课时？填写名称后，系统会先创建课时，再将本文件归入该课时。
                </span>
              </label>
            )}
            {!hasLessonPlacement(selectedLesson) && (
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
                      setWeek(event.target.value);
                      setError('');
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
                      setLessonNumber(event.target.value);
                      setError('');
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
                      setHours(event.target.value);
                      setError('');
                    }}
                  />
                </label>
              </div>
            )}
          </div>
        )}
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
              (!lessonId && !newTitle.trim()) ||
              !Number.isInteger(Number(week)) ||
              Number(week) < 1 ||
              Number(week) > 100 ||
              !Number.isInteger(Number(lessonNumber)) ||
              Number(lessonNumber) < 1 ||
              Number(lessonNumber) > 1000 ||
              !Number.isFinite(Number(hours)) ||
              Number(hours) <= 0 ||
              Number(hours) > 24
            }
            onClick={() => void publish()}
          >
            {busy ? '正在发布…' : '确认发布'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
