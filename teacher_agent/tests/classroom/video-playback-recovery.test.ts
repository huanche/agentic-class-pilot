import { describe, expect, it } from 'vitest';
import { freshVideoUrl, videoFailureMessage } from '@/lib/classroom-video/playback-recovery';

describe('MP4 playback recovery', () => {
  it('keeps the authorized media and existing query while replacing a stale retry nonce', () => {
    const url = new URL(
      freshVideoUrl(
        '/api/classroom-media/lesson/video/hash.mp4?version=v1&_playbackRetry=1',
        'https://example.com/classroom-player/lesson',
        2,
      ),
    );
    expect(url.origin).toBe('https://example.com');
    expect(url.pathname).toBe('/api/classroom-media/lesson/video/hash.mp4');
    expect(url.searchParams.get('version')).toBe('v1');
    expect(url.searchParams.getAll('_playbackRetry')).toEqual(['2']);
  });
  it('does not mislabel an expired session as a broken codec', () => {
    expect(videoFailureMessage(4, 401)).toContain('登录已过期');
    expect(videoFailureMessage(4, 403)).toContain('访问');
    expect(videoFailureMessage(4, 404)).toContain('联系老师');
    expect(videoFailureMessage(4, 503)).toContain('服务暂时不可用');
  });
  it('distinguishes transport and decoder errors when the endpoint is reachable', () => {
    expect(videoFailureMessage(2, 206)).toContain('传输中断');
    expect(videoFailureMessage(3, 206)).toContain('解码');
    expect(videoFailureMessage(2, undefined, true)).toContain('网络已断开');
  });
});
