'use client';
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { ArrowLeft, List, X, LoaderCircle } from 'lucide-react';
import { CourseVideoPlayer, type VideoPlaybackPreferences } from './course-video-player';
import type { ClassroomVideoManifest } from '@/lib/classroom-video/types';
import { SceneProvider } from '@/lib/contexts/scene-context';
import { SceneRenderer } from '@/components/stage/scene-renderer';
import { useStageStore } from '@/lib/store/stage';
import { postPlayerHostEvent } from '@/lib/integration/player-host-events';
import { postSaasHostMessage } from '@/lib/integration/host-bridge';
import { InteractiveIframeHost } from '@/components/scene-renderers/InteractiveIframeHost';
import styles from './course-video-player.module.css';
import { TrialNarrationReview } from './trial-narration-review';
import { CoursePageNavigation } from './course-page-navigation';

const SCENE_LABELS = { slide: '课程视频', interactive: '互动练习', quiz: '测验', pbl: '项目实践' };

export function ClassroomVideoViewer({
  id,
  draft,
  returnTo,
  initial,
  embedded = false,
  trial = false,
}: {
  id: string;
  draft: boolean;
  returnTo?: string | null;
  initial?: ClassroomVideoManifest;
  embedded?: boolean;
  trial?: boolean;
}) {
  const [manifest, setManifest] = useState(initial);
  const [previewRequest, setPreviewRequest] = useState<{ retry?: true | string }>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [index, setIndex] = useState(0);
  const [preferences, setPreferences] = useState<VideoPlaybackPreferences>({
    rate: 1,
    volume: 1,
    muted: false,
    captions: true,
  });
  const [autoPlay, setAutoPlay] = useState(false);
  const [videoSize, setVideoSize] = useState<{ url: string; ratio: number }>();
  const playerFrame = useRef<HTMLElement>(null);
  const viewer = useRef<HTMLElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const catalogue = useRef<HTMLDialogElement>(null);
  const [catalogueOpen, setCatalogueOpen] = useState(false);
  const openCatalogue = () => {
    catalogue.current?.showModal();
    setCatalogueOpen(true);
  };
  const closeCatalogue = () => {
    catalogue.current?.close();
    setCatalogueOpen(false);
  };
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === playerFrame.current);
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  const updatePreferences = useCallback((patch: Partial<VideoPlaybackPreferences>) => {
    setPreferences((current) =>
      Object.entries(patch).every(
        ([key, value]) => current[key as keyof VideoPlaybackPreferences] === value,
      )
        ? current
        : { ...current, ...patch },
    );
  }, []);
  const prepare = useCallback(
    async (retry?: true | string) => {
      setBusy(true);
      setError('');
      try {
        const r = await fetch(`/api/classroom?id=${encodeURIComponent(id)}`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            operation: retry ? 'retry-video' : 'prepare-video',
            ...(typeof retry === 'string' && { sceneId: retry }),
          }),
        });
        const body = await r.json();
        if (!r.ok) throw new Error(body.details || body.error || '视频转换失败');
        return body.version as string;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [id],
  );
  useEffect(() => {
    let cancelled = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async (version?: string, schedule = true) => {
      try {
        const r = await fetch(
          `/api/classroom?id=${encodeURIComponent(id)}&video=${draft ? 'draft' : 'published'}${version ? `&version=${version}` : ''}`,
          { cache: 'no-store' },
        );
        const body = await r.json();
        if (!r.ok) throw new Error(body.details || body.error || '视频读取失败');
        if (cancelled) return;
        setManifest(body.manifest || undefined);
        if (
          schedule &&
          body.manifest &&
          ['queued', 'rendering'].includes(body.manifest.status.state)
        )
          timer = setTimeout(() => void poll(version), 2500);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void (async () => {
      // An automatically prepared draft may already have playable pages.
      if (draft && !previewRequest.retry) await poll(undefined, false);
      if (cancelled) return;
      const version = draft ? await prepare(previewRequest.retry) : undefined;
      if (!cancelled) await poll(version);
    })();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id, draft, prepare, previewRequest]);
  useEffect(() => {
    if (!manifest) return;
    useStageStore.setState({
      stage: manifest.stage,
      scenes: manifest.scenes,
      currentSceneId: manifest.scenes[index]?.id || null,
      mode: 'playback',
      generationComplete: true,
    });
  }, [manifest, index]);
  const scene = manifest?.scenes[index];
  const ready = manifest?.status.state === 'ready';
  const clip =
    ready || (scene && draft && manifest?.status.readySceneIds?.includes(scene.id))
      ? manifest?.clips.find((c) => c.sceneId === scene?.id)
      : undefined;
  const workspace = manifest && (draft || ready) ? manifest : undefined;
  const sceneFailures = manifest?.status.failedPages;
  const failedCount = Object.keys(sceneFailures ?? {}).length;
  const pageFailure =
    scene && Object.hasOwn(sceneFailures ?? {}, scene.id) ? sceneFailures?.[scene.id] : undefined;
  const navigate = (next: number) => {
    setIndex(next);
    setAutoPlay(true);
    setError('');
    closeCatalogue();
    if (!document.fullscreenElement && window.matchMedia('(max-width: 1023px)').matches)
      requestAnimationFrame(() =>
        playerFrame.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }),
      );
  };
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement === playerFrame.current) await document.exitFullscreen();
      else await playerFrame.current?.requestFullscreen();
    } catch {
      setError('未能进入全屏，请重试');
    }
  };
  const sceneKind = scene ? SCENE_LABELS[scene.type] : '课程视频';
  const advance = () => {
    if (scene && scene.type !== 'quiz') postPlayerHostEvent('SCENE_COMPLETED', scene.id);
    if (manifest && index < manifest.scenes.length - 1) {
      setAutoPlay(true);
      setIndex(index + 1);
    } else {
      setAutoPlay(false);
      postPlayerHostEvent('PLAYBACK_ENDED');
    }
  };
  const theater = !embedded && Boolean(clip);
  const ratio = videoSize && videoSize.url === clip?.url ? videoSize.ratio : 16 / 9;
  useEffect(() => {
    if (!embedded || !ready) return;
    postPlayerHostEvent('PLAYER_READY');
  }, [embedded, ready]);
  useEffect(() => {
    const element = viewer.current;
    if (!embedded || fullscreen || !element) return;
    const reportHeight = () => {
      postSaasHostMessage('PLAYER_LAYOUT', {
        height: Math.ceil(element.getBoundingClientRect().height),
      });
    };
    const observer = new ResizeObserver(reportHeight);
    observer.observe(element);
    reportHeight();
    return () => observer.disconnect();
  }, [embedded, fullscreen]);
  const preparationPhase = manifest?.status.phase;
  const loadingSource = preparationPhase === 'loading';
  return (
    <main
      ref={viewer}
      className={styles.viewer}
      data-embedded={embedded}
      data-theater={theater}
      style={{ '--course-video-ratio': ratio } as CSSProperties}
    >
      <header className={styles.viewerHeader}>
        {draft && (
          <a
            href={
              returnTo?.startsWith('/') && !returnTo.startsWith('//') ? returnTo : '/course-space'
            }
            className={styles.backLink}
            aria-label="返回工作区"
          >
            <ArrowLeft size={18} />
          </a>
        )}
        {theater ? (
          <div className={styles.theaterTitles}>
            <p className={styles.courseTitle}>{manifest?.title}</p>
            <h1>{scene?.title}</h1>
          </div>
        ) : (
          <strong className={styles.courseTitle}>
            {(embedded && scene?.title) || manifest?.title || '课程课堂'}
          </strong>
        )}
        {workspace && (
          <button
            type="button"
            className={styles.catalogueToggle}
            onClick={openCatalogue}
            aria-haspopup="dialog"
            aria-expanded={catalogueOpen}
          >
            <List size={17} />
            <span>课程目录</span>
          </button>
        )}
      </header>
      {draft && (trial || manifest?.stage.coursewareTrial) && (
        <TrialNarrationReview
          classroomId={id}
          index={index}
          onSelect={(next) => {
            setIndex(next);
            setAutoPlay(false);
          }}
          onSaved={() => setPreviewRequest({})}
        />
      )}
      {error && (!ready || !clip) && (
        <p role="alert" className="my-4 rounded-xl bg-red-50 p-4 text-red-700">
          {error}
        </p>
      )}
      {!workspace ? (
        <section
          className="mx-auto mt-20 max-w-xl rounded-2xl border bg-white p-8"
          data-video-preparation-phase={
            manifest?.status.state === 'failed' ? 'failed' : preparationPhase || 'queued'
          }
          aria-busy={manifest?.status.state !== 'failed'}
        >
          {manifest?.status.state !== 'failed' && (
            <LoaderCircle
              className="mb-4 size-7 animate-spin text-[#9b2d58]"
              aria-label="正在准备视频"
            />
          )}
          <h2 className="text-xl font-semibold">
            {manifest?.status.state === 'failed'
              ? '视频转换中断'
              : loadingSource
                ? '正在加载原稿'
                : preparationPhase === 'recording'
                  ? '正在录制课件'
                  : preparationPhase === 'encoding'
                    ? '正在合成 MP4'
                    : '正在准备视频'}
          </h2>
          <p className="mt-3 text-slate-600">
            {loadingSource
              ? '原稿、字体和播放控制加载完成后，将自动开始录制。'
              : manifest
                ? `已完成 ${manifest.status.completed}/${manifest.status.total} 页`
                : busy
                  ? '正在读取最新课件和配音…'
                  : '尚无可播放的视频'}
          </p>
          {manifest?.status.currentSceneId && (
            <p className="mt-2 text-sm text-slate-600">
              {loadingSource
                ? '正在加载：'
                : preparationPhase === 'encoding'
                  ? '正在合成：'
                  : '当前页面：'}
              {manifest.scenes.find((s) => s.id === manifest.status.currentSceneId)?.title}
            </p>
          )}
          <p className="mt-3 text-sm text-slate-500">
            {loadingSource
              ? manifest && manifest.status.completed > 0
                ? `已完成 ${manifest.status.completed}/${manifest.status.total} 页，其余页面准备后继续。`
                : '正在等待加载完成，尚未开始录制。'
              : '首次转换需要录制动画和讲解；已完成的页面会复用。'}
          </p>
          {manifest?.status.error && <p className="mt-3 text-red-700">{manifest.status.error}</p>}
          {draft && (error || manifest?.status.state === 'failed') && (
            <button
              disabled={busy}
              className="mt-5 rounded-lg bg-[#a51b57] px-4 py-2 text-white"
              onClick={() => setPreviewRequest({ retry: true })}
            >
              重试未完成视频
            </button>
          )}
        </section>
      ) : (
        <div className={styles.viewerWorkspace}>
          {draft && !ready && (
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border bg-background px-4 py-2 text-sm">
              <span>
                已完成 {workspace.status.completed}/{workspace.status.total} 页
                {failedCount > 0 && ' · 失败 ' + failedCount + ' 页'}
                {workspace.status.state === 'failed' &&
                  !failedCount &&
                  workspace.status.error &&
                  ' · ' + workspace.status.error}
              </span>
              {workspace.status.state === 'failed' && (
                <button
                  type="button"
                  disabled={busy}
                  className="font-medium text-primary underline-offset-4 hover:underline disabled:opacity-60"
                  onClick={() => setPreviewRequest({ retry: true })}
                >
                  重试未完成视频
                </button>
              )}
            </div>
          )}
          {!theater && (
            <div className={styles.lessonHeading}>
              <div className={styles.lessonMeta}>
                <span>{sceneKind}</span>
                <i />
                <span>
                  {String(index + 1).padStart(2, '0')} / {workspace.scenes.length}
                </span>
              </div>
              <h1>{scene?.title}</h1>
            </div>
          )}
          <section ref={playerFrame} data-course-player-frame className={styles.frame}>
            <div className={styles.frameBody}>
              {clip ? (
                <CourseVideoPlayer
                  key={`${workspace.version}:${scene?.id}`}
                  src={clip.url}
                  title={scene?.title || workspace.title}
                  autoPlay={autoPlay}
                  fullscreenTarget={playerFrame}
                  isFullscreen={fullscreen}
                  preferences={preferences}
                  captions={clip.captions}
                  onAspectRatio={(next) => setVideoSize({ url: clip.url, ratio: next })}
                  onPrevious={fullscreen && index > 0 ? () => navigate(index - 1) : undefined}
                  onNext={
                    fullscreen && index < workspace.scenes.length - 1
                      ? () => navigate(index + 1)
                      : undefined
                  }
                  onPreferencesChange={updatePreferences}
                  onEnded={advance}
                  onError={setError}
                  onPlay={() => setError('')}
                />
              ) : scene?.type === 'slide' ? (
                <div
                  className="flex min-h-52 flex-col items-center justify-center gap-3 p-5 text-center"
                  data-video-preparation-phase={
                    pageFailure
                      ? 'failed'
                      : workspace.status.currentSceneId === scene.id
                        ? preparationPhase || 'queued'
                        : 'queued'
                  }
                  aria-busy={
                    !pageFailure && ['queued', 'rendering'].includes(workspace.status.state)
                  }
                >
                  <p className="font-semibold">
                    {pageFailure
                      ? '本页视频转换失败'
                      : workspace.status.currentSceneId === scene.id
                        ? loadingSource
                          ? '正在加载本页原稿'
                          : preparationPhase === 'encoding'
                            ? '正在合成本页 MP4'
                            : '正在录制本页'
                        : '本页视频待转换'}
                  </p>
                  {pageFailure && <p className="max-w-lg text-sm text-red-700">{pageFailure}</p>}
                  {draft && (pageFailure || workspace.status.state === 'failed') && (
                    <button
                      type="button"
                      disabled={busy}
                      className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-60"
                      onClick={() => setPreviewRequest({ retry: scene.id })}
                    >
                      重试本页
                    </button>
                  )}
                </div>
              ) : (
                scene && (
                  <div className={styles.activity} data-course-activity={scene.type}>
                    <div className={styles.activityBody}>
                      <SceneProvider>
                        <SceneRenderer
                          scene={scene}
                          mode="playback"
                          studentPlayer={!draft}
                          onSceneComplete={advance}
                        />
                      </SceneProvider>
                    </div>
                  </div>
                )
              )}
            </div>
            {(!clip || !fullscreen) && (
              <CoursePageNavigation
                index={index}
                total={workspace.scenes.length}
                fullscreen={fullscreen}
                onPrevious={() => navigate(index - 1)}
                onNext={() =>
                  scene && ['interactive', 'pbl'].includes(scene.type)
                    ? advance()
                    : navigate(index + 1)
                }
                onFullscreen={clip ? undefined : () => void toggleFullscreen()}
              />
            )}
            {/* Stable sibling of every scene: keep the interactive document alive
                across chapters and inside the same fullscreen ancestor. */}
            <InteractiveIframeHost key={id} />
          </section>
          {!theater && (
            <p className={styles.lessonCaption}>
              {scene?.type === 'interactive'
                ? '操作完成后，点击“下一页”进入下一节。'
                : scene?.type === 'quiz'
                  ? '提交答案后可查看解析。'
                  : scene?.type === 'pbl'
                    ? '完成实践后继续学习。'
                    : '可拖动进度回看，也可调整播放速度。'}
            </p>
          )}
          {index === workspace.scenes.length - 1 &&
            scene &&
            ['interactive', 'pbl'].includes(scene.type) && (
              <button type="button" className={styles.activityPrimary} onClick={advance}>
                完成课程
              </button>
            )}
          <dialog
            ref={catalogue}
            className={styles.catalogue}
            aria-labelledby="catalogue-title"
            onClose={() => setCatalogueOpen(false)}
            onClick={(event) => {
              if (event.target === event.currentTarget) closeCatalogue();
            }}
          >
            <div className={styles.catalogueHeader}>
              <h2 id="catalogue-title">课程目录</h2>
              <button
                type="button"
                onClick={closeCatalogue}
                className={styles.activityButton}
                aria-label="收起目录"
              >
                <X size={18} />
              </button>
            </div>
            <div className={styles.catalogueCourse}>
              {workspace.title}
              <span>
                共 {workspace.scenes.length} 节 · 当前第 {index + 1} 节
              </span>
            </div>
            <nav aria-label="课程目录" className={styles.catalogueList}>
              {workspace.scenes.map((s, i) => (
                <button
                  key={s.id}
                  aria-current={i === index ? 'step' : undefined}
                  onClick={() => navigate(i)}
                  className={`${styles.chapter} ${i === index ? styles.chapterActive : ''}`}
                >
                  <span className={styles.chapterNumber}>{String(i + 1).padStart(2, '0')}</span>
                  <span className="min-w-0 break-words leading-5">
                    {s.title}
                    {s.type !== 'slide' ? (
                      <small className={styles.chapterKind}>{SCENE_LABELS[s.type]}</small>
                    ) : draft && !ready ? (
                      <small className={styles.chapterKind}>
                        {workspace.status.readySceneIds?.includes(s.id)
                          ? '可播放'
                          : Object.hasOwn(sceneFailures ?? {}, s.id)
                            ? '转换失败'
                            : workspace.status.currentSceneId === s.id
                              ? '转换中'
                              : '待转换'}
                      </small>
                    ) : null}
                  </span>
                </button>
              ))}
            </nav>
          </dialog>
        </div>
      )}
    </main>
  );
}
