import {
  INTEGRATION_PROTOCOL_VERSION,
  type IntegrationEnvelope,
  type IntegrationSource,
} from './messages.js';

function messageId() {
  return globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createIntegrationMessage<TType extends string, TPayload>(
  source: IntegrationSource,
  type: TType,
  payload: TPayload,
): IntegrationEnvelope<TType, TPayload> {
  return {
    version: INTEGRATION_PROTOCOL_VERSION,
    id: messageId(),
    type,
    source,
    timestamp: Date.now(),
    payload,
  };
}

export function postIntegrationMessage<TType extends string, TPayload>(
  target: Window,
  targetOrigin: string,
  source: IntegrationSource,
  type: TType,
  payload: TPayload,
) {
  if (!targetOrigin || targetOrigin === '*') throw new Error('A concrete targetOrigin is required');
  target.postMessage(createIntegrationMessage(source, type, payload), targetOrigin);
}
