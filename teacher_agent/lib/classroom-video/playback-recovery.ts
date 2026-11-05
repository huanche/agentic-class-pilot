/** Keep a retry on the same authorized MP4, while bypassing a damaged HTTP cache entry. */
export function freshVideoUrl(source: string, base: string, nonce: number) {
  const url = new URL(source, base);
  url.searchParams.set('_playbackRetry', String(nonce));
  return url.href;
}

export function videoFailureMessage(code: number, status?: number, offline = false) {
  if (status === 401) return '登录已过期，请重新登录后播放。';
  if (status === 403) return '暂时无法访问这段视频，请重新打开课程。';
  if (status === 404) return '这段视频暂时不可用，请联系老师检查课件。';
  if (status && status >= 500) return '视频服务暂时不可用，请稍后重新加载。';
  if (offline) return '网络已断开，请连接网络后重新加载。';
  if (code === 2) return '视频传输中断，请重新加载后继续播放。';
  if (code === 3) return '浏览器未能解码这段视频，请重新加载。';
  return '这段视频暂时无法播放，请重新加载。';
}
