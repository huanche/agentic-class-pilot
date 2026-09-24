import { INTEGRATION_PROTOCOL_VERSION, type IntegrationEnvelope } from './messages.js';

export function isIntegrationEnvelope(value: unknown): value is IntegrationEnvelope {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return record.version === INTEGRATION_PROTOCOL_VERSION
    && typeof record.id === 'string'
    && typeof record.type === 'string'
    && typeof record.source === 'string'
    && typeof record.timestamp === 'number'
    && 'payload' in record;
}

export function assertTrustedMessage(event: MessageEvent, allowedOrigin: string) {
  return event.origin === allowedOrigin && isIntegrationEnvelope(event.data);
}
