import { describe, expect, it } from 'vitest';
import { createCaptureReadinessGate } from '@/lib/classroom-video/capture-readiness';

const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
describe('recording readiness gate', () => {
  it('blocks recording before native source, fonts and images complete', async () => {
    const gate = createCaptureReadinessGate(),
      source = deferred(),
      fonts = deferred(),
      images = deferred();
    const preparing = gate.prepare('s1', async () => {
      await source.promise;
      await fonts.promise;
      await images.promise;
    });
    expect(() => gate.assertReady('s1')).toThrow('仍在加载');
    source.resolve();
    await Promise.resolve();
    expect(() => gate.assertReady('s1')).toThrow();
    fonts.resolve();
    await Promise.resolve();
    expect(() => gate.assertReady('s1')).toThrow();
    images.resolve();
    await preparing;
    expect(() => gate.assertReady('s1')).not.toThrow();
  });
  it('does not authorize a recording after loading failed', async () => {
    const gate = createCaptureReadinessGate();
    await expect(
      gate.prepare('s', async () => {
        throw Error('原稿错误');
      }),
    ).rejects.toThrow('原稿错误');
    expect(() => gate.assertReady('s')).toThrow();
  });
  it('rejects a late previous-page response and invalidates prepared state on teardown', async () => {
    const gate = createCaptureReadinessGate(),
      old = deferred();
    const pending = gate.prepare('old', () => old.promise);
    await gate.prepare('new', async () => {});
    old.resolve();
    await expect(pending).rejects.toThrow('页面已切换');
    expect(() => gate.assertReady('new')).not.toThrow();
    expect(() => gate.assertReady('old')).toThrow();
    gate.invalidate();
    expect(() => gate.assertReady('new')).toThrow();
  });
});
