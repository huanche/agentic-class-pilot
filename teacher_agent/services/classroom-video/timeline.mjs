import { promises as fs } from 'node:fs';
import path from 'node:path';
import { unzipSync } from 'fflate';

/** Trusted app-generated project, still bound its extraction and filesystem paths. */
export async function unpackTimelineProject(base64, directory) {
  if (typeof base64 !== 'string' || base64.length > 180 * 1024 * 1024)
    throw new Error('动画项目过大');
  const bytes = Buffer.from(base64, 'base64');
  let expanded = 0,
    entries = 0;
  const files = unzipSync(bytes, {
    filter(file) {
      if (
        ++entries > 5000 ||
        file.originalSize > 64 * 1024 * 1024 ||
        (expanded += file.originalSize) > 300 * 1024 * 1024
      )
        throw new Error('动画项目解压大小超出限制');
      return true;
    },
  });
  if (!files['index.html']) throw new Error('动画项目缺少 index.html');
  const root = path.resolve(directory);
  for (const [name, data] of Object.entries(files)) {
    if (
      name.includes('\\') ||
      name.includes('\0') ||
      name.startsWith('/') ||
      name.split('/').some((part) => part === '..') ||
      /^[A-Za-z]:/.test(name)
    )
      throw new Error('动画项目路径无效');
    const target = path.resolve(root, name);
    if (!target.startsWith(root + path.sep)) throw new Error('动画项目路径越界');
    if (name.endsWith('/')) {
      await fs.mkdir(target, { recursive: true });
      continue;
    }
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, data);
  }
}

/** Same producer API as OpenMAIC's render-service; never waits for real-time playback. */
export async function renderTimelineProject(project, directory, output, onPhase) {
  await unpackTimelineProject(project.projectBase64, directory);
  const { createRenderJob, executeRenderJob } = await import('@hyperframes/producer');
  const job = createRenderJob({ fps: 30, quality: 'standard', format: 'mp4', workers: 1 });
  await onPhase('rendering');
  let lastPhase = 'rendering';
  await executeRenderJob(
    job,
    directory,
    output,
    (current) => {
      const phase = ['encoding', 'assembling'].includes(current.status)
        ? 'encoding'
        : current.status === 'rendering'
          ? 'rendering'
          : undefined;
      if (phase && phase !== lastPhase) {
        lastPhase = phase;
        return onPhase(phase);
      }
    },
    AbortSignal.timeout(30 * 60 * 1000),
  );
  if (job.status !== 'complete') throw new Error(job.error || '动画时间轴渲染未完成');
  return {
    renderer: 'openmaic-timeline-v1',
    frames: Math.round(project.duration * 30),
    workers: 1,
    ...(job.perfSummary ? { performance: job.perfSummary } : {}),
  };
}
