/** Save the embedded editor before asking the server to hash/render its document. */
export async function flushEmbeddedClassroom(frame: HTMLIFrameElement, classroomId: string) {
  const requestId = crypto.randomUUID();
  await new Promise<void>((resolve, reject) => {
    const finish = (error?: Error) => {
      clearTimeout(timer);
      window.removeEventListener('message', receive);
      if (error) reject(error);
      else resolve();
    };
    const receive = (event: MessageEvent) => {
      const m = event.data;
      if (
        event.origin !== location.origin ||
        event.source !== frame.contentWindow ||
        m?.channel !== 'classroom-video-flush' ||
        m.requestId !== requestId ||
        m.classroomId !== classroomId
      )
        return;
      if (m.event === 'saved') finish();
      else if (m.event === 'error') finish(new Error(m.error || '保存课件失败'));
    };
    const timer = setTimeout(() => finish(new Error('保存课件超时，请稍后重试')), 45_000);
    window.addEventListener('message', receive);
    frame.contentWindow?.postMessage(
      { channel: 'classroom-video-flush', classroomId, requestId },
      location.origin,
    );
  });
}
