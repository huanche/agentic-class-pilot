'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { NativePptxView } from '@/components/stage/native-pptx-view';
import { nativeDriver, nativePptxPage } from '@/lib/onlyoffice/native-player';
import type { Scene, Stage } from '@/lib/types/stage';
import { trialSpeechAudio } from '@/lib/generation/courseware-trial';
import { isNativeClick } from '@/lib/onlyoffice/narration';

export function TrialNarrationReview({
  classroomId,
  index,
  onSelect,
  onSaved,
}: {
  classroomId: string;
  index: number;
  onSelect: (index: number) => void;
  onSaved: () => void;
}) {
  const [classroom, setClassroom] = useState<{ stage: Stage; scenes: Scene[] }>();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [originalSceneId, setOriginalSceneId] = useState<string>();
  const [step, setStep] = useState(0);
  const [seeking, setSeeking] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void fetch('/api/classroom?id=' + encodeURIComponent(classroomId), {
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.details || data.error || '读取试用草稿失败');
        if (!controller.signal.aborted && data.classroom?.stage?.coursewareTrial) {
          setClassroom({
            ...data.classroom,
            scenes: [...data.classroom.scenes].sort((a, b) => a.order - b.order),
          });
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason.message ?? reason));
      });
    return () => controller.abort();
  }, [classroomId, reload]);
  const stage = classroom?.stage;
  const trial = stage?.coursewareTrial;
  const scene = classroom?.scenes[index];
  const showOriginal = !!scene && originalSceneId === scene.id;
  const hasNative = Boolean(nativePptxPage(stage, scene));
  const clicks = hasNative ? (stage?.nativePptx?.clicks?.[scene?.outlineId ?? ''] ?? []) : [];
  const speech = (scene?.actions ?? []).filter((action) => action.type === 'speech');
  const hasEdits = speech.some(({ id }) => Object.hasOwn(edits, id));
  async function save(regenerate = false) {
    if (busy || !trial?.courseId || !scene) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetch(
        '/api/course-space/' +
          encodeURIComponent(trial.courseId) +
          '/classrooms/' +
          encodeURIComponent(classroomId) +
          '/narration',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            operation: 'trial-revise',
            sceneId: scene.id,
            revision: trial.revision ?? 0,
            segments: Object.fromEntries(
              speech.flatMap(({ id }) => (Object.hasOwn(edits, id) ? [[id, edits[id]]] : [])),
            ),
            regenerate,
            revoice: !regenerate && !hasEdits,
          }),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.details || data.error || '更新讲稿失败');
      setEdits({});
      setReload((value) => value + 1);
      onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  if (!classroom || !trial) {
    return error ? <p role="alert">{error}</p> : null;
  }
  return (
    <details
      className="mx-auto my-4 w-full max-w-5xl rounded-xl border bg-background p-4"
      data-trial-narration
    >
      <summary className="cursor-pointer font-medium">逐页讲稿与原稿检查</summary>
      <div className="mt-4 grid gap-4 md:grid-cols-[14rem_minmax(0,1fr)]">
        <nav aria-label="试用课件目录" className="max-h-64 space-y-1 overflow-y-auto">
          {classroom.scenes.map((page, i) => {
            const missing =
              page.type === 'slide' &&
              (!page.actions?.some((action) => action.type === 'speech') ||
                page.actions.some(
                  (action) => action.type === 'speech' && !trialSpeechAudio(action),
                ));
            const native = stage?.nativePptx?.clicks?.[page.outlineId ?? ''];
            const alignment =
              nativePptxPage(stage, page) &&
              native &&
              page.actions?.filter(
                (action) =>
                  action.type === 'reveal' && action.pptxStep && isNativeClick(action.pptxStep.id),
              ).length !== native.length;
            return (
              <button
                type="button"
                key={page.id}
                disabled={busy || seeking}
                aria-current={i === index ? 'page' : undefined}
                onClick={() => {
                  onSelect(i);
                  setEdits({});
                  setOriginalSceneId(undefined);
                  setStep(0);
                }}
                className={
                  'block w-full rounded-md p-2 text-left text-sm ' +
                  (i === index ? 'bg-muted font-medium' : 'hover:bg-muted')
                }
              >
                {i + 1}. {page.title}
                {(missing || alignment) && (
                  <span className="block text-xs text-amber-700">
                    {[missing && '缺配音', alignment && '动画待核对'].filter(Boolean).join(' · ')}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
        <section className="min-w-0 space-y-3">
          {scene?.type === 'slide' && (
            <>
              {hasNative && (
                <Button
                  variant="outline"
                  type="button"
                  onClick={() => {
                    setOriginalSceneId(showOriginal ? undefined : scene.id);
                    setStep(0);
                  }}
                >
                  {showOriginal ? '收起原稿' : '看原稿动画'}
                </Button>
              )}
              {showOriginal && hasNative && (
                <>
                  <div className="aspect-video overflow-hidden rounded-md border">
                    <NativePptxView scene={scene} sourceStageId={classroomId} />
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={seeking || step >= clicks.length}
                      onClick={async () => {
                        const driver = nativeDriver(scene.id);
                        if (!driver) return;
                        setSeeking(true);
                        try {
                          await driver.seek(step + 1);
                          setStep(step + 1);
                        } catch {
                          setError('原稿动画播放失败，请重新打开原稿');
                        } finally {
                          setSeeking(false);
                        }
                      }}
                    >
                      播放下一步
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {step} / {clicks.length}
                    </span>
                  </div>
                </>
              )}
              {speech.map((segment, i) => (
                <div key={segment.id} className="space-y-1">
                  <label
                    className="block text-xs text-muted-foreground"
                    htmlFor={'trial-' + segment.id}
                  >
                    讲稿第 {i + 1} 段
                  </label>
                  <textarea
                    id={'trial-' + segment.id}
                    disabled={busy}
                    rows={3}
                    maxLength={2000}
                    value={edits[segment.id] ?? segment.text}
                    onChange={(event) => setEdits({ ...edits, [segment.id]: event.target.value })}
                    className="w-full rounded-md border bg-background p-2 text-sm"
                  />
                  {trialSpeechAudio(segment) && (
                    <audio
                      aria-label={'试听第 ' + (i + 1) + ' 段配音'}
                      controls
                      preload="none"
                      src={trialSpeechAudio(segment)}
                      className="h-9 w-full max-w-sm"
                    />
                  )}
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" disabled={busy || !speech.length} onClick={() => void save()}>
                  {busy ? '更新中…' : hasEdits ? '保存并更新本页配音' : '用优化读法重新配音'}
                </Button>
                <Button
                  type="button"
                  disabled={busy}
                  variant="outline"
                  onClick={() => void save(true)}
                >
                  重新生成本页讲稿
                </Button>
              </div>
            </>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
        </section>
      </div>
    </details>
  );
}
