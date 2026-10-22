'use client';

import { useState } from 'react';
import type { Scene, Stage } from '@/lib/types/stage';
import { assessCourseDuration } from '@/lib/generation/course-duration';
import { MAX_COURSE_DURATION_CORRECTIONS } from '@/lib/generation/course-duration-calibration';
import { calibrateCompletedCourse } from '@/lib/hooks/use-scene-generator';
import { useStageStore } from '@/lib/store';
import { formatPlaybackDuration } from '@/lib/playback/timing-display';

export function CourseDurationSummary({ stage, scenes }: { stage: Stage | null; scenes: Scene[] }) {
  const generationStatus = useStageStore((state) => state.generationStatus);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState('');
  if (stage?.timing?.budgetVersion !== 1) return null;
  const report = assessCourseDuration(
    scenes,
    stage.timing.targetDurationMinutes!,
    stage.timing.expectedAutomaticPages ?? 0,
  );
  const status = {
    unmeasured: '尚未完成实测',
    'within-tolerance': '达标',
    'too-short': '偏短',
    'too-long': '偏长',
  }[report.status];
  const targetOnly = stage.timing.durationPolicy === 'target';
  const busy =
    !targetOnly && (running || (report.actualSeconds != null && generationStatus === 'generating'));
  const needsCorrection =
    !targetOnly && report.actualSeconds != null && report.status !== 'within-tolerance';
  const attempts = stage.timing.courseCorrectionAttempts ?? 0;
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-xs tabular-nums text-violet-700 dark:text-violet-300">
      <span
        title={
          targetOnly
            ? '目标时长用于组织教学内容，实际时长以配音与演示实测为准；不含自主答题和教师暂停，不会为凑时长反复生成。'
            : '正常语速下的自动讲解与演示。配音实测加已知同步动作时长；不含网络等待、教师暂停、自主答题和自由讨论。单页及整课各最多校正两轮，容差 ±5%；只采用总偏差更小的配音版本。视频或白板时长未测量时不会报告达标。'
        }
      >
        目标 {stage.timing.targetDurationMinutes} 分钟 ·{' '}
        {report.actualSeconds == null
          ? `已测 ${report.measuredPages}/${report.expectedPages} 页 · ${status}`
          : `实测 ${formatPlaybackDuration(report.actualSeconds)}${targetOnly ? '' : ` · ${status}`}`}
      </span>
      {busy && <span>整课校正中…</span>}
      {needsCorrection && !busy && attempts < MAX_COURSE_DURATION_CORRECTIONS && (
        <button
          type="button"
          className="rounded border border-violet-300 px-2 py-1 hover:bg-violet-50 dark:hover:bg-violet-950"
          onClick={async () => {
            setRunning(true);
            setMessage('');
            try {
              const result = await calibrateCompletedCourse();
              if (!result.changed)
                setMessage(
                  result.attempts
                    ? '本轮未改善，已保留原课件。'
                    : '请先切换到其他页面，或完成缺失的配音。',
                );
            } catch {
              setMessage('校正未完成，已保留原课件。');
            } finally {
              setRunning(false);
            }
          }}
        >
          校正整课时长
        </button>
      )}
      {needsCorrection && !busy && attempts >= MAX_COURSE_DURATION_CORRECTIONS && (
        <span>已完成两轮整课校正</span>
      )}
      {message && <span role="status">{message}</span>}
    </span>
  );
}
