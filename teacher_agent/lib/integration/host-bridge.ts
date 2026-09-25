const PROTOCOL_VERSION = '1.0' as const;

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

export function postSaasHostMessage<TPayload>(type: string, payload: TPayload) {
  if (typeof window === 'undefined' || window.parent === window) return false;
  const targetOrigin = configuredHostOrigin();
  if (!targetOrigin) return false;
  window.parent.postMessage({
    version: PROTOCOL_VERSION,
    id: globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}`,
    type,
    source: 'teacher-workspace',
    timestamp: Date.now(),
    payload,
  }, targetOrigin);
  return true;
}
