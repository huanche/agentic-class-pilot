import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import JSZip from 'jszip';
import type { CourseMaterialRecord } from '@/lib/course-space/types';
import { COURSE_SPACES_DIR, readCourseMaterialBytes } from './course-space-storage';
import {
  isCourseObjectStorageEnabled,
  putCourseObject,
  readCourseObject,
} from './course-object-storage';
import { resolveApiKey, resolveASRApiKey, resolveImageApiKey } from './provider-config';
import { getPptxPageImage } from './pptx-page-image';

export interface PptPageOcrResult {
  title: string;
  content: string;
  model: string;
}

const archives = new Map<string, Promise<JSZip>>();
const pending = new Map<string, Promise<PptPageOcrResult>>();
let active = 0;
const waiters: Array<() => void> = [];

async function archive(material: CourseMaterialRecord) {
  const key = material.sha256 || material.storageKey;
  let promise = archives.get(key);
  if (!promise) {
    promise = readCourseMaterialBytes(material).then((bytes) => JSZip.loadAsync(bytes));
    archives.set(key, promise);
    if (archives.size > 2) archives.delete(archives.keys().next().value!);
    promise.catch(() => archives.delete(key));
  }
  return promise;
}

export async function readPptPagePreview(material: CourseMaterialRecord, page: number) {
  return getPptxPageImage(await archive(material), page);
}

export async function recognizePptImage(
  image: Buffer,
  signal?: AbortSignal,
): Promise<PptPageOcrResult> {
  const key =
    process.env.PPTX_OCR_API_KEY?.trim() ||
    resolveApiKey('qwen') ||
    resolveASRApiKey('qwen-asr') ||
    resolveImageApiKey('qwen-image');
  if (!key) throw new Error('尚未配置图片文字识别服务，请联系管理员配置 Qwen OCR');
  const model = process.env.PPTX_OCR_MODEL?.trim() || 'qwen-vl-ocr';
  const base =
    process.env.PPTX_OCR_BASE_URL?.trim() || 'https://dashscope.aliyuncs.com/compatible-mode/v1';
  const response = await fetch(`${base.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    signal: AbortSignal.any([AbortSignal.timeout(60000), ...(signal ? [signal] : [])]),
    headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      model,
      temperature: 0,
      max_tokens: 8192,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'image_url',
              image_url: { url: `data:image/jpeg;base64,${image.toString('base64')}` },
            },
            { type: 'text', text: 'Read all the text in the image.' },
          ],
        },
      ],
    }),
  });
  // Do not forward upstream messages: a proxy may include credentials or request details.
  if (!response.ok) throw new Error(`图片文字识别服务暂时不可用（${response.status}），请重试`);
  const data = await response.json();
  const choice = data.choices?.[0];
  if (choice?.finish_reason !== 'stop' || typeof choice.message?.content !== 'string') {
    throw new Error('本页识别结果不完整，请重试');
  }
  const text = choice.message.content.trim();
  if (!text || text.length > 50000) throw new Error('未识别到本页文字，请核对原图或重试');
  const lines = text
    .split('\n')
    .map((line: string) => line.trim())
    .filter(Boolean);
  const heading =
    lines.find((line: string) => /^#{1,6}\s/.test(line)) ||
    lines.find((line: string) => /^第[\d一二三四五六七八九十]+章/.test(line)) ||
    lines[0];
  return { title: heading.replace(/^#+\s*/, '').slice(0, 80), content: text, model };
}

/** Per-source, per-page cache survives refreshes and is shared by both conversion modes. */
export async function recognizePptPage(
  material: CourseMaterialRecord,
  page: number,
  signal?: AbortSignal,
) {
  if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
  const identity = createHash('sha256')
    .update(material.sha256 || material.storageKey)
    .digest('hex');
  const model = process.env.PPTX_OCR_MODEL?.trim() || 'qwen-vl-ocr';
  const version = createHash('sha256').update(`v1:${model}`).digest('hex').slice(0, 12);
  const key = `pptx-ocr/${identity}/${version}/page-${page}.json`;
  const file = path.join(COURSE_SPACES_DIR, key);
  const stored = isCourseObjectStorageEnabled()
    ? await readCourseObject(key)
    : await fs.readFile(file).catch((error) => {
        if (error.code !== 'ENOENT') throw error;
        return null;
      });
  if (stored) {
    const result = JSON.parse(stored.toString()) as PptPageOcrResult;
    if (
      typeof result.title === 'string' &&
      typeof result.content === 'string' &&
      result.content.trim()
    )
      return result;
  }
  // Coalesce duplicate requests. Only the owner signal cancels the shared OCR;
  // another viewer can retry immediately after an owner cancellation.
  if (pending.has(key)) return pending.get(key)!;
  const job = (async () => {
    if (active >= 3) await new Promise<void>((resolve) => waiters.push(resolve));
    active++;
    try {
      if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
      const result = await recognizePptImage(await readPptPagePreview(material, page), signal);
      const bytes = Buffer.from(JSON.stringify(result));
      if (isCourseObjectStorageEnabled()) await putCourseObject(key, bytes, 'application/json');
      else {
        await fs.mkdir(path.dirname(file), { recursive: true });
        const temporary = `${file}.${randomUUID()}.tmp`;
        await fs.writeFile(temporary, bytes);
        await fs.rename(temporary, file);
      }
      return result;
    } finally {
      active--;
      waiters.shift()?.();
    }
  })();
  pending.set(key, job);
  try {
    return await job;
  } finally {
    pending.delete(key);
  }
}
