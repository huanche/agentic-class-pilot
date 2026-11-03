// 与 SaaS 宿主页通信的唯一出口。信封结构（IntegrationEnvelope）与协议版本
// 统一引自 packages/integration-contract/src/messages.ts —— 全仓只维护这一份
// 协议定义，不再手抄（问题2.3）。monorepo 内相对引用源码，避免 lockfile 变更；
// 上游若发布该包，可改为对 @mentra/integration-contract 的常规依赖。
import {
  INTEGRATION_PROTOCOL_VERSION,
  type IntegrationEnvelope,
} from '../../packages/integration-contract/src/messages';

function configuredHostOrigin() {
  const value = process.env.NEXT_PUBLIC_SAAS_HOST_ORIGIN?.trim();
  if (value && value !== '*') {
    try {
      return new URL(value).origin;
    } catch {
      // Fall through to the actual embedding document's origin.
    }
  }
  if (typeof document !== 'undefined' && document.referrer) {
    try {
      return new URL(document.referrer).origin;
    } catch {
      return undefined;
    }
  }
  return undefined;
}

export function postSaasHostMessage<TType extends string, TPayload>(
  type: TType,
  payload: TPayload,
): boolean {
  if (typeof window === 'undefined' || window.parent === window) return false;
  const targetOrigin = configuredHostOrigin();
  if (!targetOrigin) return false;
  const envelope: IntegrationEnvelope<TType, TPayload> = {
    version: INTEGRATION_PROTOCOL_VERSION,
    id: globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}`,
    type,
    source: 'teacher-workspace',
    timestamp: Date.now(),
    payload,
  };
  window.parent.postMessage(envelope, targetOrigin);
  return true;
}
