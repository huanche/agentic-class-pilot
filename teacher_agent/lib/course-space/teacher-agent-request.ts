import type { CourseArtifactJob } from './types';
import type { ThinkingConfig } from '@/lib/types/provider';
import type { BaiduSubSources, WebSearchProviderId } from '@/lib/web-search/types';

type ModelConfig = {
  modelString: string; apiKey: string; baseUrl: string;
  providerType?: string; thinkingConfig?: ThinkingConfig;
};
type Turn = {
  sessionId: string; message: string;
  history: Array<{ role: 'user' | 'assistant'; content: string }>;
  attachments: Array<{ name: string; mimeType: string; dataUrl: string }>;
  scope: CourseArtifactJob['scope']; deepInteraction: boolean;
};

/** The same tested client chain is used by manual messages and external prompts. */
export async function requestTeacherAgentTurn(input: {
  courseId: string;
  modelConfig: ModelConfig;
  body: Turn;
  webSearch?: {
    providerId: WebSearchProviderId;
    providerConfig?: { apiKey?: string; baseUrl?: string; modelId?: string };
    baiduSubSources?: BaiduSubSources;
  };
}) {
  const { modelConfig, webSearch } = input;
  const headers = {
    'content-type': 'application/json',
    'x-model': modelConfig.modelString, 'x-api-key': modelConfig.apiKey,
    'x-base-url': modelConfig.baseUrl, 'x-provider-type': modelConfig.providerType || '',
  };
  let webContext: string | undefined;
  if (webSearch) {
    const response = await fetch('/api/web-search', {
      method: 'POST', headers,
      body: JSON.stringify({
        query: input.body.message, providerId: webSearch.providerId,
        apiKey: webSearch.providerConfig?.apiKey, baseUrl: webSearch.providerConfig?.baseUrl,
        claudeModelId: webSearch.providerConfig?.modelId,
        baiduSubSources: webSearch.providerId === 'baidu' ? webSearch.baiduSubSources : undefined,
        thinkingConfig: modelConfig.thinkingConfig,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) {
      throw new Error(typeof data.error === 'string' ? data.error : data.error?.message || '网页检索失败');
    }
    const context = data.data?.context ?? data.context;
    webContext = typeof context === 'string' ? context.slice(0, 24000) : undefined;
  }
  return fetch(`/api/course-space/${encodeURIComponent(input.courseId)}/agent`, {
    method: 'POST', headers,
    body: JSON.stringify({ ...input.body, webContext, thinkingConfig: modelConfig.thinkingConfig }),
  });
}