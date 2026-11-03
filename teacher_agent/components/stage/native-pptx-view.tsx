'use client';
import { useEffect, useRef, useState } from 'react';
import type { Scene } from '@/lib/types/stage';
import { useStageStore } from '@/lib/store/stage';
import { registerNativeDriver } from '@/lib/onlyoffice/native-player';

const CHANNEL = 'agentic-native-pptx-v1';
interface NativePptxViewProps {
  scene: Scene;
  preview?: boolean;
  loadTimeoutMs?: number;
}

export function NativePptxView(props: NativePptxViewProps) {
  const [attempt, setAttempt] = useState(0);
  return (
    <NativePptxSession
      key={`${props.scene.id}:${attempt}`}
      {...props}
      onRetry={() => setAttempt((value) => value + 1)}
    />
  );
}

function NativePptxSession({
  scene,
  preview = false,
  onRetry,
  loadTimeoutMs = 45000,
}: NativePptxViewProps & { onRetry: () => void }) {
  const stageId = useStageStore((s) => s.stage?.id);
  const previewSteps = useStageStore(
    (s) => s.stage?.nativePptx?.clicks?.[scene.outlineId || '']?.length ?? 0,
  );
  const frame = useRef<HTMLIFrameElement>(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    let connected = false;
    let resolve!: () => void, reject!: (reason: Error) => void;
    const loaded = new Promise<void>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    void loaded.catch(() => {});
    const fail = (error: Error) => {
      if (disposed) return;
      reject(error);
      setError(error.message);
    };
    let id = 0;
    const pending = new Map<
      number,
      { resolve: () => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> }
    >();
    const send = (command: string, step?: number) =>
      new Promise<void>((yes, no) => {
        const number = ++id;
        const timer = setTimeout(() => {
          pending.delete(number);
          no(new Error('原稿动画命令超时'));
        }, 60000);
        pending.set(number, { resolve: yes, reject: no, timer });
        frame.current?.contentWindow?.postMessage(
          { channel: CHANNEL, id: number, command, step, sceneId: scene.id },
          location.origin,
        );
      });
    const fire = (command: string) => {
      void loaded.then(() => send(command)).catch(fail);
    };
    const receive = (event: MessageEvent) => {
      if (
        event.origin !== location.origin ||
        event.source !== frame.current?.contentWindow ||
        event.data?.channel !== CHANNEL
      )
        return;
      if (event.data.sceneId !== scene.id) return;
      if (event.data.event === 'ready') {
        connected = true;
        resolve();
        // The workspace previews the completed source page, not the reflowed
        // editable canvas. The playback view still starts before click one.
        if (preview) {
          void send('seek', previewSteps)
            .then(() => setReady(true))
            .catch(fail);
        } else {
          setReady(true);
        }
      }
      if (event.data.event === 'error') {
        const e = new Error(event.data.detail || '原稿加载失败');
        fail(e);
      }
      const item = pending.get(event.data.id);
      if (item && ['ack', 'error'].includes(event.data.event)) {
        clearTimeout(item.timer);
        pending.delete(event.data.id);
        if (event.data.event === 'ack') item.resolve();
        else item.reject(new Error(event.data.detail));
      }
    };
    window.addEventListener('message', receive);
    const unregister = preview
      ? () => {}
      : registerNativeDriver(scene.id, {
          ready: loaded,
          seek: async (step) => {
            await loaded;
            await send('seek', step);
          },
          pause: () => fire('pause'),
          resume: () => fire('resume'),
          reset: () => fire('reset'),
        });
    void fetch('/onlyoffice/status', { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((status) => {
        if (status?.enabled === false) {
          fail(new Error('原稿播放服务暂不可用，请重试'));
        }
      })
      .catch(() => {});
    const timeout = setTimeout(() => {
      if (!connected) {
        fail(new Error('原稿加载超时，请重新加载'));
      }
    }, loadTimeoutMs);
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timeout);
      unregister();
      window.removeEventListener('message', receive);
      for (const item of pending.values()) {
        clearTimeout(item.timer);
        item.reject(new Error('页面已切换'));
      }
      reject(new Error('页面已切换'));
    };
    // A scene owns its iframe/controller; switching pages cannot ack an old scene.
  }, [scene.id, preview, previewSteps, loadTimeoutMs]);
  return (
    <div className="relative h-full w-full bg-white" data-native-pptx="onlyoffice">
      <iframe
        ref={frame}
        title="PPTX 原稿放映"
        className="pointer-events-none h-full w-full border-0"
        src={`/onlyoffice/frame?classroom=${encodeURIComponent(stageId || '')}&scene=${encodeURIComponent(scene.id)}`}
        allow="autoplay; fullscreen"
      />
      {ready && !error && (
        <div className="absolute right-2 top-2 flex items-center gap-2 rounded bg-white/90 px-2 py-1 text-[10px] text-slate-500">
          <span>原稿 · ONLYOFFICE</span>
        </div>
      )}
      {!ready && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-white">
          正在加载原稿…
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white p-6 text-sm"
        >
          <p>{error}</p>
          <button
            className="rounded border px-3 py-2"
            onClick={(event) => {
              event.stopPropagation();
              onRetry();
            }}
          >
            重新加载
          </button>
        </div>
      )}
    </div>
  );
}
