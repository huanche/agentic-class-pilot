'use client';

import { useId } from 'react';
import { resolveCourseMinutes } from '@/lib/generation/course-duration';

export function courseDurationInputError(value: string): string | undefined {
  try {
    resolveCourseMinutes(value);
    return undefined;
  } catch (error) {
    return (error as Error).message;
  }
}

export function CourseDurationInput({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const error = courseDurationInputError(value);
  return (
    <div className="space-y-1.5 text-sm">
      <label htmlFor={id} className="flex flex-wrap items-center gap-2 font-medium">
        课件播放时长
        <input
          id={id}
          type="number"
          min="1"
          step="1"
          value={value}
          placeholder="默认 28"
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-hint`}
          className="w-28 rounded-md border bg-background px-3 py-1.5 font-normal outline-none focus:border-violet-500"
        />
        <span className="text-xs font-normal text-muted-foreground">分钟（选填）</span>
      </label>
      <p
        id={`${id}-hint`}
        className={error ? 'text-xs text-red-600' : 'text-xs text-muted-foreground'}
      >
        {error ||
          '留空默认 28 分钟，用于安排自动讲解与演示。实际时长以生成的配音为准，不含自主答题、自由讨论或教师暂停。'}
      </p>
    </div>
  );
}
