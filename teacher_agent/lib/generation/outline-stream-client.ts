import type { SceneOutline } from '@/lib/types/generation';

/** Consume the same outline SSE endpoint for a teacher-requested revision. */
export async function readOutlineStream(response: Response) {
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `大纲生成失败（${response.status}）`);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('无法读取大纲生成结果');
  const decoder = new TextDecoder();
  let buffer = '';
  let outlines: SceneOutline[] = [];
  let languageDirective = '';
  let courseTitle: string | undefined;
  let taskEngineMode = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split('\n');
      buffer = done ? '' : lines.pop()!;
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const event = JSON.parse(line.slice(5).trim());
        if (event.type === 'error') throw new Error(event.error || '大纲生成失败');
        if (event.type === 'retry') {
          outlines = [];
          languageDirective = '';
          courseTitle = undefined;
        }
        if (event.type === 'outline') outlines.push(event.data);
        if (event.type === 'languageDirective') languageDirective = event.data;
        if (event.type === 'courseTitle') courseTitle = event.data;
        if (event.type === 'done') {
          outlines = event.outlines ?? outlines;
          languageDirective = event.languageDirective || languageDirective;
          courseTitle = event.courseTitle || courseTitle;
          taskEngineMode = event.taskEngineMode === true || event.effectiveTaskEngineMode === true;
          if (!outlines.length) throw new Error('模型未返回可用的大纲，原大纲已保留，请重试。');
          return { outlines, languageDirective, courseTitle, taskEngineMode };
        }
      }
      if (done) break;
    }
    throw new Error('大纲生成连接中断，原大纲已保留，请重试。');
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
