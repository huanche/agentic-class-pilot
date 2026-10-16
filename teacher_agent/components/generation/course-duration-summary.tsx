import type { Scene, Stage } from '@/lib/types/stage';
import { assessCourseDuration } from '@/lib/generation/course-duration';
import { formatPlaybackDuration } from '@/lib/playback/timing-display';

export function CourseDurationSummary({ stage, scenes }: { stage: Stage | null; scenes: Scene[] }) {
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
  return (
    <span
      className="text-xs tabular-nums text-violet-700 dark:text-violet-300"
      title="正常语速下的自动讲解与演示。配音实测加已知同步动作时长；不含网络等待、教师暂停、自主答题和自由讨论。校正最多两轮，容差 ±5%；未达标可调整讲稿后重新生成。视频或白板时长未测量时不会报告达标。"
    >
      目标 {stage.timing.targetDurationMinutes} 分钟 ·{' '}
      {report.actualSeconds == null
        ? `已测 ${report.measuredPages}/${report.expectedPages} 页 · ${status}`
        : `实测 ${formatPlaybackDuration(report.actualSeconds)} · ${status}`}
    </span>
  );
}
