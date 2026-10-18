import { resolveStoredBytes } from '@/lib/media/resolve-stored-bytes';
import type { BackgroundCoursewareInput } from './background-courseware';

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('读取课件素材失败'));
    reader.readAsDataURL(blob);
  });
}

/** A server worker must never depend on this tab's blob URLs or IndexedDB refs. */
export async function prepareBackgroundInput(input: BackgroundCoursewareInput) {
  const urls = new Map<string, Promise<string>>();
  const visit = async (value: unknown): Promise<unknown> => {
    if (typeof value === 'string' && /^(?:blob:|ast_)/.test(value)) {
      if (!urls.has(value))
        urls.set(
          value,
          (async () => {
            const blob = value.startsWith('blob:')
              ? await fetch(value).then((response) => response.blob())
              : await resolveStoredBytes(value, {
                  stageId: input.stage.id,
                  loadCompatRow: true,
                  taskUrlFallback: true,
                  fetchPolicy: { requireOk: true, requireNonEmpty: true },
                });
            if (!blob?.size) throw new Error('课件素材缺失，请重新导入后再提交后台生成');
            return dataUrl(blob);
          })(),
        );
      return urls.get(value)!;
    }
    if (Array.isArray(value)) return Promise.all(value.map(visit));
    if (value && typeof value === 'object')
      return Object.fromEntries(
        await Promise.all(
          Object.entries(value).map(async ([key, item]) => [key, await visit(item)]),
        ),
      );
    return value;
  };
  const prepared = (await visit(input)) as BackgroundCoursewareInput;
  prepared.pdfImages = prepared.pdfImages?.map((image) => ({
    ...image,
    src: image.src || prepared.imageMapping?.[image.id] || '',
  }));
  return prepared;
}
