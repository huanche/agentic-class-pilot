'use client';

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from 'react';
import {
  Maximize,
  Minimize,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  Check,
  LoaderCircle,
  Captions,
} from 'lucide-react';
import styles from './course-video-player.module.css';
import { freshVideoUrl, videoFailureMessage } from '@/lib/classroom-video/playback-recovery';
import { captionCueText, type VideoCaption } from '@/lib/classroom-video/captions';

export interface VideoPlaybackPreferences {
  rate: number;
  volume: number;
  muted: boolean;
  captions: boolean;
}

interface CourseVideoPlayerProps {
  src: string;
  title: string;
  autoPlay?: boolean;
  preferences: VideoPlaybackPreferences;
  onPreferencesChange: (patch: Partial<VideoPlaybackPreferences>) => void;
  onEnded: () => void;
  onPlay: () => void;
  onError: (message: string) => void;
  onPrevious?: () => void;
  onNext?: () => void;
  fullscreenTarget?: RefObject<HTMLElement | null>;
  isFullscreen?: boolean;
  captions?: VideoCaption[];
  hideFullscreenControl?: boolean;
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const HIDE_CONTROLS_AFTER_MS = 3000;
const clamp = (value: number, max = 1) => Math.min(max, Math.max(0, value));
function clock(seconds: number) {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(value % 60).padStart(2, '0')}`;
}

/** The full-screen target owns both picture and controls, including speed. */
export function CourseVideoPlayer({
  src,
  title,
  autoPlay,
  preferences,
  onPreferencesChange,
  onEnded,
  onPlay,
  onError,
  onPrevious,
  onNext,
  fullscreenTarget,
  isFullscreen,
  captions,
  hideFullscreenControl,
}: CourseVideoPlayerProps) {
  const root = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const subtitleTrack = useRef<TextTrack | null>(null);
  const [captionText, setCaptionText] = useState('');
  const speedMenu = useRef<HTMLDivElement>(null);
  const speedButton = useRef<HTMLButtonElement>(null);
  const controls = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pinned = useRef(true);
  const keyboardModality = useRef(false);
  const touchWakeOnly = useRef(false);
  const pointerType = useRef('mouse');
  const controlPointerDown = useRef(false);
  const [mediaSrc, setMediaSrc] = useState(src);
  const failureProbe = useRef<AbortController | null>(null);
  const retryCount = useRef(0);
  const resumeTime = useRef(0);
  const retryPosition = useRef(0);
  const playbackWanted = useRef(Boolean(autoPlay));
  const restorePlayback = useRef(false);
  const [paused, setPaused] = useState(true);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [buffered, setBuffered] = useState<{ start: number; end: number }[]>([]);
  const [waiting, setWaiting] = useState(true);
  const [failed, setFailed] = useState(false);
  const [failureMessage, setFailureMessage] = useState('');
  const [failureCode, setFailureCode] = useState('');
  const [slow, setSlow] = useState(false);
  const [localFullscreen, setFullscreen] = useState(false);
  const fullscreen = isFullscreen ?? localFullscreen;
  const [speedOpen, setSpeedOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const [controlsVisible, setControlsVisible] = useState(true);
  const [keyboardFocus, setKeyboardFocus] = useState(false);
  const [dragging, setDragging] = useState(false);
  const controlsPinned =
    paused || waiting || failed || speedOpen || keyboardFocus || dragging || Boolean(notice);
  const controlsShown = controlsPinned || controlsVisible;
  useEffect(() => {
    const player = video.current;
    if (!player || typeof VTTCue === 'undefined') return;
    const track = subtitleTrack.current || player.addTextTrack('subtitles', '中文讲稿', 'zh-CN');
    subtitleTrack.current = track;
    track.mode = 'hidden';
    for (const cue of Array.from(track.cues || [])) track.removeCue(cue);
    for (const caption of captions || []) {
      const cue = new VTTCue(caption.start, caption.end, captionCueText(caption.text));
      cue.size = 90;
      cue.align = 'center';
      track.addCue(cue);
    }
    return () => {
      track.mode = 'disabled';
    };
  }, [captions]);
  useEffect(() => {
    const track = subtitleTrack.current;
    if (!track) return;
    // The browser owns timing (including seek/rate changes). Render the active
    // text in our frame so responsive wrapping and control avoidance are stable.
    const update = () =>
      setCaptionText(
        preferences.captions
          ? Array.from(track.activeCues || [])
              .map((cue) => (cue as VTTCue).getCueAsHTML().textContent || '')
              .join('\n')
          : '',
      );
    track.mode = preferences.captions ? 'hidden' : 'disabled';
    track.addEventListener('cuechange', update);
    update();
    return () => track.removeEventListener('cuechange', update);
  }, [captions, preferences.captions]);
  useEffect(() => () => failureProbe.current?.abort(), []);
  useEffect(() => {
    if (!waiting || failed) return;
    const timer = setTimeout(() => setSlow(true), 12000);
    return () => clearTimeout(timer);
  }, [waiting, failed]);

  const retryVideo = () => {
    failureProbe.current?.abort();
    retryCount.current++;
    retryPosition.current = resumeTime.current;
    restorePlayback.current = true;
    setFailed(false);
    setSlow(false);
    setWaiting(true);
    setNotice('');
    setBuffered([]);
    setMediaSrc(freshVideoUrl(src, location.href, Date.now()));
  };
  const diagnoseFailure = async () => {
    const player = video.current;
    if (!player?.error) return;
    const code = player.error.code;
    setFailed(true);
    setPaused(true);
    setWaiting(false);
    setFailureMessage(videoFailureMessage(code, undefined, !navigator.onLine));
    setFailureCode(`媒体错误 ${code}`);
    failureProbe.current?.abort();
    const controller = new AbortController();
    failureProbe.current = controller;
    const timer = setTimeout(() => controller.abort(), 6000);
    try {
      const r = await fetch(freshVideoUrl(src, location.href, Date.now()), {
        headers: { Range: 'bytes=0-0' },
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      await r.body?.cancel();
      if (controller.signal.aborted) return;
      const isVideo = r.ok && r.headers.get('content-type')?.startsWith('video/');
      // Recover one interrupted/cached response. Never retry auth failures or
      // loop forever on an unsupported stream. Manual retry remains available.
      if (isVideo && retryCount.current === 0 && [2, 3, 4].includes(code)) {
        retryVideo();
        return;
      }
      const message = videoFailureMessage(code, r.status, !navigator.onLine);
      setFailureMessage(message);
      setFailureCode(`媒体错误 ${code} · HTTP ${r.status}${isVideo ? '' : ' · 视频响应异常'}`);
      onError(message);
    } catch {
      if (!controller.signal.aborted) {
        const message = videoFailureMessage(code, undefined, !navigator.onLine);
        setFailureMessage(message);
        onError(message);
      }
    } finally {
      clearTimeout(timer);
    }
  };
  const clearHideTimer = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = null;
  }, []);
  const scheduleHide = useCallback(() => {
    clearHideTimer();
    if (!pinned.current)
      hideTimer.current = setTimeout(() => setControlsVisible(false), HIDE_CONTROLS_AFTER_MS);
  }, [clearHideTimer]);
  const revealControls = useCallback(() => {
    setControlsVisible(true);
    scheduleHide();
  }, [scheduleHide]);

  useEffect(() => {
    pinned.current = controlsPinned;
    scheduleHide();
    return clearHideTimer;
  }, [controlsPinned, scheduleHide, clearHideTimer]);

  useEffect(() => {
    const keyboard = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Tab') keyboardModality.current = true;
    };
    const pointer = () => {
      keyboardModality.current = false;
    };
    document.addEventListener('keydown', keyboard, true);
    document.addEventListener('pointerdown', pointer, true);
    return () => {
      document.removeEventListener('keydown', keyboard, true);
      document.removeEventListener('pointerdown', pointer, true);
    };
  }, []);

  useEffect(() => {
    const released = () => {
      if (!controlPointerDown.current) return;
      controlPointerDown.current = false;
      setDragging(false);
      revealControls();
    };
    window.addEventListener('pointerup', released, true);
    window.addEventListener('pointercancel', released, true);
    return () => {
      window.removeEventListener('pointerup', released, true);
      window.removeEventListener('pointercancel', released, true);
    };
  }, [revealControls]);

  useEffect(() => {
    const player = video.current;
    if (!player) return;
    if (player.playbackRate !== preferences.rate) player.playbackRate = preferences.rate;
    if (player.volume !== preferences.volume) player.volume = preferences.volume;
    if (player.muted !== preferences.muted) player.muted = preferences.muted;
  }, [preferences.rate, preferences.volume, preferences.muted]);

  useEffect(() => {
    const changed = () => {
      setFullscreen(document.fullscreenElement === (fullscreenTarget?.current || root.current));
      revealControls();
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, [revealControls, fullscreenTarget]);

  useEffect(() => {
    if (!speedOpen) return;
    const outside = (event: PointerEvent) => {
      if (!speedMenu.current?.contains(event.target as Node)) {
        setSpeedOpen(false);
        revealControls();
      }
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSpeedOpen(false);
        revealControls();
        speedButton.current?.focus();
      }
    };
    speedMenu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [speedOpen, revealControls]);

  const togglePlay = async () => {
    revealControls();
    const player = video.current;
    if (!player || failed) return;
    if (!player.paused) {
      playbackWanted.current = false;
      player.pause();
      return;
    }
    if (player.ended) player.currentTime = 0;
    playbackWanted.current = true;
    try {
      await player.play();
      setNotice('');
    } catch {
      setNotice('点击播放按钮继续播放');
    }
  };
  const seek = (position: number) => {
    revealControls();
    if (!video.current || !duration) return;
    const next = clamp(position, duration);
    video.current.currentTime = next;
    setTime(next);
  };
  const toggleFullscreen = async () => {
    revealControls();
    try {
      const target = fullscreenTarget?.current || root.current;
      if (document.fullscreenElement === target) await document.exitFullscreen();
      else if (target?.requestFullscreen) await target.requestFullscreen();
      else setNotice('当前浏览器暂不支持全屏');
    } catch {
      setNotice('未能进入全屏，请重试');
    }
  };
  const shortcut = (event: KeyboardEvent<HTMLDivElement>) => {
    if (
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      (event.target as HTMLElement).closest('input,select,textarea,[contenteditable="true"]')
    )
      return;
    // Space belongs to a focused button; F/M/arrows still control the player
    // after a mouse click leaves focus on the play or fullscreen button.
    if (event.key === ' ' && (event.target as HTMLElement).closest('button')) return;
    switch (event.key.toLowerCase()) {
      case ' ':
      case 'k':
        event.preventDefault();
        void togglePlay();
        break;
      case 'arrowleft':
        event.preventDefault();
        seek(time - 5);
        break;
      case 'arrowright':
        event.preventDefault();
        seek(time + 5);
        break;
      case 'arrowup':
        event.preventDefault();
        onPreferencesChange({ volume: clamp(preferences.volume + 0.05), muted: false });
        break;
      case 'arrowdown':
        event.preventDefault();
        onPreferencesChange({ volume: clamp(preferences.volume - 0.05) });
        break;
      case 'm':
        event.preventDefault();
        onPreferencesChange({ muted: !preferences.muted });
        break;
      case 'f':
        event.preventDefault();
        void toggleFullscreen();
        break;
      case 'escape':
        setSpeedOpen(false);
        break;
    }
  };
  const progress = duration ? clamp(time / duration) * 100 : 0;
  const control =
    'inline-flex size-9 shrink-0 items-center justify-center rounded-md text-white/85 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-default disabled:opacity-25';

  return (
    <div
      ref={root}
      data-course-video-player
      role="region"
      aria-label={`${title}视频播放器`}
      tabIndex={0}
      onKeyDown={shortcut}
      onKeyDownCapture={() => {
        keyboardModality.current = true;
        setKeyboardFocus(true);
        revealControls();
      }}
      onPointerMove={revealControls}
      onPointerDownCapture={(event) => {
        pointerType.current = event.pointerType;
        touchWakeOnly.current = event.pointerType === 'touch' && !controlsShown;
        keyboardModality.current = false;
        setKeyboardFocus(false);
        revealControls();
      }}
      onFocusCapture={() => {
        if (keyboardModality.current) {
          setKeyboardFocus(true);
          revealControls();
        }
      }}
      onBlurCapture={(event) => {
        if (keyboardFocus && !event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setKeyboardFocus(false);
          revealControls();
        }
      }}
      className={`relative flex w-full flex-col overflow-hidden rounded-xl bg-[#101114] text-white outline-none focus-visible:ring-2 focus-visible:ring-[#c93678] ${fullscreen ? 'min-h-0 flex-1 rounded-none' : ''} ${!controlsShown ? 'cursor-none' : ''}`}
    >
      <div
        className={`relative overflow-hidden bg-black ${fullscreen ? 'min-h-0 flex-1' : styles.videoSurface} ${failed ? styles.failedSurface : ''}`}
      >
        <video
          ref={video}
          src={mediaSrc}
          aria-label={title}
          playsInline
          preload="metadata"
          autoPlay={autoPlay}
          className={`${styles.videoElement} absolute inset-0 size-full object-contain`}
          onClick={() => {
            if (touchWakeOnly.current) {
              touchWakeOnly.current = false;
              revealControls();
              return;
            }
            void togglePlay();
          }}
          onDoubleClick={() => {
            if (pointerType.current !== 'touch') void toggleFullscreen();
          }}
          onLoadedMetadata={() => {
            const player = video.current!;
            setDuration(Number.isFinite(player.duration) ? player.duration : 0);
            player.playbackRate = preferences.rate;
            player.volume = preferences.volume;
            player.muted = preferences.muted;
            setFailed(false);
            setFailureMessage('');
            if (restorePlayback.current) {
              restorePlayback.current = false;
              player.currentTime = Math.min(
                retryPosition.current,
                Math.max(0, player.duration - 0.1),
              );
              if (playbackWanted.current)
                void player.play().catch(() => setNotice('点击播放按钮继续播放'));
            }
          }}
          onTimeUpdate={() => {
            const position = video.current?.currentTime || 0;
            setTime(position);
            // load() emits a synthetic timeupdate at zero before the new
            // metadata arrives. It must not erase the retry checkpoint.
            if (video.current && !video.current.error && video.current.readyState >= 2)
              resumeTime.current = position;
          }}
          onProgress={() => {
            const ranges = video.current?.buffered;
            setBuffered(
              ranges
                ? Array.from({ length: ranges.length }, (_, i) => ({
                    start: ranges.start(i),
                    end: ranges.end(i),
                  }))
                : [],
            );
          }}
          onPlay={() => {
            playbackWanted.current = true;
            setPaused(false);
            setFailed(false);
            revealControls();
            onPlay();
          }}
          onPause={() => {
            setPaused(true);
            revealControls();
          }}
          onWaiting={() => setWaiting(true)}
          onSeeking={() => setWaiting(true)}
          onCanPlay={() => {
            setSlow(false);
            setWaiting(false);
            revealControls();
          }}
          onSeeked={() => {
            setWaiting(false);
            revealControls();
          }}
          onPlaying={() => {
            setWaiting(false);
            revealControls();
          }}
          onRateChange={() => {
            if (
              video.current &&
              video.current.readyState >= 1 &&
              !restorePlayback.current &&
              video.current.playbackRate !== preferences.rate
            )
              onPreferencesChange({ rate: video.current.playbackRate });
          }}
          onVolumeChange={() => {
            const player = video.current;
            if (
              player &&
              (player.volume !== preferences.volume || player.muted !== preferences.muted)
            )
              onPreferencesChange({ volume: player.volume, muted: player.muted });
          }}
          onEnded={() => {
            setPaused(true);
            onEnded();
          }}
          onError={() => void diagnoseFailure()}
        />
        {preferences.captions && captionText && !failed && (
          <div
            data-course-captions
            className={styles.captionsOverlay}
            data-controls-shown={controlsShown}
            aria-live="off"
          >
            <span>{captionText}</span>
          </div>
        )}
        {failed ? (
          <div className={styles.videoRecovery} role="alert">
            <RotateCcw className="size-7 text-slate-400" />
            <h2>视频暂时无法播放</h2>
            <p>{failureMessage}</p>
            <div>
              <button className={styles.activityPrimary} onClick={retryVideo}>
                重新加载视频
              </button>
              {onNext && (
                <button className={styles.activityButton} onClick={onNext}>
                  先学下一节 →
                </button>
              )}
            </div>
            <details>
              <summary>查看错误信息</summary>
              {failureCode}
            </details>
          </div>
        ) : waiting ? (
          <div role="status" className={styles.videoWaiting}>
            <LoaderCircle className="size-8 animate-spin" />
            <span>{slow ? '视频加载较慢，可以重新加载后继续。' : '正在加载视频…'}</span>
            {slow && (
              <button className={styles.activityPrimary} onClick={retryVideo}>
                重新加载视频
              </button>
            )}
          </div>
        ) : (
          paused &&
          (!preferences.captions || time < 0.1) && (
            <button
              aria-label="播放视频"
              className="absolute inset-0 m-auto grid size-16 place-items-center rounded-full border border-white/20 bg-black/35 text-white shadow-lg backdrop-blur-sm transition hover:scale-105 hover:bg-black/50"
              onClick={() => void togglePlay()}
            >
              <Play className="ml-1 size-7 fill-current" />
            </button>
          )
        )}
      </div>
      {/* Overlay visibility never changes the picture bounds or video scale. */}
      <div
        ref={controls}
        data-player-controls
        data-visible={controlsShown}
        aria-hidden={!controlsShown}
        inert={!controlsShown}
        onPointerDownCapture={() => {
          controlPointerDown.current = true;
          setDragging(true);
          revealControls();
        }}
        className={`${styles.controls} ${!controlsShown ? styles.controlsHidden : ''} px-3 pb-2 sm:px-4`}
      >
        <div className="relative flex h-5 items-center">
          <div className="pointer-events-none absolute inset-x-0 h-1 overflow-hidden rounded-full bg-white/15">
            {duration > 0 &&
              buffered.map((range) => (
                <span
                  key={range.start}
                  className="absolute h-full bg-white/25"
                  style={{
                    left: `${(range.start / duration) * 100}%`,
                    width: `${((range.end - range.start) / duration) * 100}%`,
                  }}
                />
              ))}
            <span
              className="absolute inset-y-0 left-0 bg-[#d73b81]"
              style={{ width: `${progress}%` }}
            />
          </div>
          <input
            className={styles.seek}
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={Math.min(time, duration)}
            disabled={!duration || failed}
            aria-label="播放进度"
            aria-valuetext={`${clock(time)} / ${clock(duration)}`}
            onChange={(event) => seek(Number(event.target.value))}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-0.5 sm:gap-1">
            <button
              className={control}
              disabled={failed}
              title={paused ? '播放（空格）' : '暂停（空格）'}
              aria-label={paused ? '播放' : '暂停'}
              onClick={() => void togglePlay()}
            >
              {paused ? (
                <Play className="size-5 fill-current" />
              ) : (
                <Pause className="size-5 fill-current" />
              )}
            </button>
            {onPrevious && (
              <span className={styles.previous}>
                <button className={control} aria-label="上一节" title="上一节" onClick={onPrevious}>
                  <SkipBack className="size-4.5" />
                </button>
              </span>
            )}
            {onNext && (
              <span className={styles.next}>
                <button className={control} aria-label="下一节" title="下一节" onClick={onNext}>
                  <SkipForward className="size-4.5" />
                </button>
              </span>
            )}
            <span
              aria-live="off"
              className="ml-1 whitespace-nowrap font-mono text-[11px] tabular-nums text-white/70 sm:ml-2 sm:text-xs"
            >
              {clock(time)} <span className="mx-0.5 text-white/35">/</span> {clock(duration)}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <button
              type="button"
              className={`${control} relative`}
              aria-label="字幕"
              aria-pressed={preferences.captions}
              title={preferences.captions ? '关闭字幕' : '开启字幕'}
              onClick={() => onPreferencesChange({ captions: !preferences.captions })}
            >
              <Captions className="size-5" />
              <span className={styles.captionIndicator} data-enabled={preferences.captions} />
            </button>
            <div className="flex items-center gap-1">
              <button
                className={control}
                title={preferences.muted || !preferences.volume ? '取消静音（M）' : '静音（M）'}
                aria-label={preferences.muted || !preferences.volume ? '取消静音' : '静音'}
                onClick={() =>
                  onPreferencesChange(
                    !preferences.volume
                      ? { volume: 0.5, muted: false }
                      : { muted: !preferences.muted },
                  )
                }
              >
                {preferences.muted || !preferences.volume ? (
                  <VolumeX className="size-5" />
                ) : (
                  <Volume2 className="size-5" />
                )}
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                aria-label="音量"
                value={preferences.muted ? 0 : preferences.volume}
                onChange={(event) =>
                  onPreferencesChange({ volume: Number(event.target.value), muted: false })
                }
                className="hidden h-1 w-16 cursor-pointer accent-white sm:block"
              />
            </div>
            <div ref={speedMenu} className="relative">
              <button
                ref={speedButton}
                className={`${control} w-auto gap-1.5 px-2 text-xs sm:text-sm`}
                aria-label={`播放速度，当前 ${preferences.rate} 倍`}
                aria-haspopup="menu"
                aria-expanded={speedOpen}
                onClick={() => setSpeedOpen(!speedOpen)}
              >
                <span className="hidden sm:inline">倍速</span>
                <span className="tabular-nums">{preferences.rate}×</span>
              </button>
              {speedOpen && (
                <div
                  role="menu"
                  aria-label="播放速度"
                  className="absolute bottom-full right-0 z-20 mb-3 grid w-52 grid-cols-3 overflow-hidden rounded-xl border border-white/10 bg-[#202125] p-1 shadow-2xl sm:block sm:w-36 sm:p-1.5"
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      event.stopPropagation();
                      setSpeedOpen(false);
                      speedButton.current?.focus();
                      return;
                    }
                    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
                    event.preventDefault();
                    event.stopPropagation();
                    const buttons = Array.from(
                      event.currentTarget.querySelectorAll<HTMLButtonElement>(
                        '[role="menuitemradio"]',
                      ),
                    );
                    const active = buttons.indexOf(document.activeElement as HTMLButtonElement);
                    const next =
                      event.key === 'Home'
                        ? 0
                        : event.key === 'End'
                          ? buttons.length - 1
                          : (active + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) %
                            buttons.length;
                    buttons[next]?.focus();
                  }}
                >
                  <p className="col-span-3 px-2 pb-1 pt-0.5 text-[11px] text-white/45 sm:px-3 sm:pb-2 sm:pt-1">
                    播放速度
                  </p>
                  {SPEEDS.map((value) => (
                    <button
                      key={value}
                      role="menuitemradio"
                      aria-checked={value === preferences.rate}
                      className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-xs text-white/85 hover:bg-white/10 focus-visible:bg-white/10 focus-visible:outline-none sm:px-3 sm:py-2 sm:text-sm"
                      onClick={() => {
                        onPreferencesChange({ rate: value });
                        setSpeedOpen(false);
                        speedButton.current?.focus();
                      }}
                    >
                      {value}×
                      {value === 1 && (
                        <span className="mr-auto hidden pl-2 text-xs text-white/45 sm:inline">
                          正常
                        </span>
                      )}
                      {value === preferences.rate && <Check className="size-4 text-[#f58cb7]" />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {!hideFullscreenControl && (
              <button
                className={control}
                aria-label={fullscreen ? '退出全屏' : '全屏'}
                title={fullscreen ? '退出全屏（F）' : '全屏（F）'}
                onClick={() => void toggleFullscreen()}
              >
                {fullscreen ? <Minimize className="size-5" /> : <Maximize className="size-5" />}
              </button>
            )}
          </div>
        </div>
        {notice && (
          <p role="status" className="pt-1 text-center text-xs text-white/65">
            {notice}
          </p>
        )}
      </div>
    </div>
  );
}
