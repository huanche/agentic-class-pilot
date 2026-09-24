'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, FolderOpen } from 'lucide-react';
import type { CourseArtifactJob, CourseSpace } from '@/lib/course-space';

type Scope = CourseArtifactJob['scope'];

function isSelected(current: Scope, option: Scope) {
  if (current.type !== option.type) return false;
  if (current.type === 'module' && option.type === 'module') return current.moduleId === option.moduleId;
  if (current.type === 'lesson' && option.type === 'lesson') return current.lessonId === option.lessonId;
  return current.type === 'course';
}

function locationLabel(course: CourseSpace, scope: Scope) {
  if (scope.type === 'course') return course.title;
  const courseModule = course.modules.find((item) =>
    scope.type === 'module'
      ? item.id === scope.moduleId
      : item.lessons.some((lesson) => lesson.id === scope.lessonId),
  );
  if (!courseModule) return course.title;
  if (scope.type === 'module') return `${course.title} / ${courseModule.title}`;
  const lesson = courseModule.lessons.find((item) => item.id === scope.lessonId);
  return lesson ? `${course.title} / ${courseModule.title} / ${lesson.title}` : course.title;
}

export function CourseWorkLocationPicker({ course, scope, onChange }: {
  course: CourseSpace;
  scope: Scope;
  onChange: (scope: Scope) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const choose = (next: Scope) => {
    onChange(next);
    setOpen(false);
  };

  return <div ref={containerRef} className="relative min-w-0">
    <button
      type="button"
      aria-label={`当前工作位置：${locationLabel(course, scope)}；点击选择文件夹`}
      aria-expanded={open}
      aria-haspopup="menu"
      onClick={() => setOpen((value) => !value)}
      className="flex max-w-[min(58vw,520px)] min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-slate-600 transition hover:bg-[#B00055]/5 focus-visible:outline-2 focus-visible:outline-[#B00055]"
    >
      <FolderOpen className="size-4 shrink-0 text-[#B00055]" />
      <span className="shrink-0">当前工作位置</span>
      <span className="truncate font-medium text-[#8F0046]" title={locationLabel(course, scope)}>{locationLabel(course, scope)}</span>
      <ChevronDown className={`size-3.5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
    </button>
    {open && <div role="menu" aria-label="选择课程工作文件夹" className="absolute right-0 top-full z-50 mt-2 w-[min(88vw,360px)] overflow-hidden rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
      <p className="px-2 py-1 text-[11px] text-slate-500">选择本课程下的工作目录</p>
      <div className="max-h-80 overflow-y-auto">
        <button type="button" role="menuitemradio" aria-checked={scope.type === 'course'} onClick={() => choose({ type: 'course' })} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs hover:bg-slate-50">
          <FolderOpen className="size-4 text-[#B00055]"/><span className="min-w-0 flex-1 truncate">{course.title}</span>{scope.type === 'course' && <Check className="size-4 text-[#B00055]"/>}
        </button>
        {course.modules.map((courseModule) => <div key={courseModule.id}>
          <button type="button" role="menuitemradio" aria-checked={isSelected(scope, { type: 'module', moduleId: courseModule.id })} onClick={() => choose({ type: 'module', moduleId: courseModule.id })} className="flex w-full items-center gap-2 rounded-lg py-2 pl-5 pr-2 text-left text-xs hover:bg-slate-50">
            <FolderOpen className="size-4 text-amber-500"/><span className="min-w-0 flex-1 truncate">{courseModule.title}</span>{isSelected(scope, { type: 'module', moduleId: courseModule.id }) && <Check className="size-4 text-[#B00055]"/>}
          </button>
          {courseModule.lessons.map((lesson) => <button key={lesson.id} type="button" role="menuitemradio" aria-checked={isSelected(scope, { type: 'lesson', lessonId: lesson.id })} onClick={() => choose({ type: 'lesson', lessonId: lesson.id })} className="flex w-full items-center gap-2 rounded-lg py-2 pl-9 pr-2 text-left text-xs hover:bg-slate-50">
            <FolderOpen className="size-3.5 text-[#B00055]"/><span className="min-w-0 flex-1 truncate">{lesson.title}</span>{isSelected(scope, { type: 'lesson', lessonId: lesson.id }) && <Check className="size-4 text-[#B00055]"/>}
          </button>)}
        </div>)}
      </div>
    </div>}
  </div>;
}
