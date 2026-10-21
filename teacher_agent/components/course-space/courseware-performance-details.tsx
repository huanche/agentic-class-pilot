import type { CoursewarePerformance } from '@/lib/generation/courseware-performance';

const labels: Record<string, string> = {
  queue: '等待生成资源',
  content: '页面画面',
  actions: '讲解与校验合计',
  'narration-plan': '其中：讲解规划',
  'focus-review': '其中：聚焦校验',
  audio: '配音（含校时重配）',
  'page-duration': '逐页校时（含重生成）',
  'course-duration': '整课校时（含重生成）',
  'context-repair': '衔接复核',
  save: '保存课件',
};
const duration = (ms: number) => {
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} 秒`;
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
};

export function CoursewarePerformanceDetails({ value }: { value?: CoursewarePerformance }) {
  if (!value) return null;
  const totals = new Map<string, { ms: number; count: number }>();
  for (const item of value.timings) {
    if (!labels[item.phase]) continue;
    const row = totals.get(item.phase) || { ms: 0, count: 0 };
    row.ms += item.durationMs;
    row.count++;
    totals.set(item.phase, row);
  }
  return (
    <details className="mt-5 rounded-lg border bg-slate-50/60 p-3 text-sm">
      <summary className="cursor-pointer text-muted-foreground">
        本次运行耗时 · {duration(value.elapsedMs)}
      </summary>
      <div className="mt-3 space-y-2">
        {value.firstPageReadyMs != null && <p>首个完整页面：{duration(value.firstPageReadyMs)}</p>}
        <p>
          音频缓存：复用 {value.audioCache.hits} 段，共享生成 {value.audioCache.shared} 段，合成请求{' '}
          {value.audioCache.misses + value.audioCache.bypassed} 次
        </p>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b">
              <th className="py-2 font-medium">阶段</th>
              <th className="font-medium">次数</th>
              <th className="font-medium">累计用时</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(labels)
              .filter((key) => totals.has(key))
              .map((key) => {
                const row = totals.get(key)!;
                return (
                  <tr key={key} className="border-b last:border-0">
                    <td className="py-1.5">{labels[key]}</td>
                    <td>{row.count}</td>
                    <td>{duration(row.ms)}</td>
                  </tr>
                );
              })}
          </tbody>
        </table>
        <p className="text-xs text-muted-foreground">
          阶段可能并行，校时也可能调用讲解和配音，累计用时不能直接相加。
        </p>
      </div>
    </details>
  );
}
