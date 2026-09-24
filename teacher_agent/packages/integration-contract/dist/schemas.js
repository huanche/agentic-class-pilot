import { INTEGRATION_PROTOCOL_VERSION } from './messages.js';
export function isIntegrationEnvelope(value) {
    if (!value || typeof value !== 'object')
        return false;
    const record = value;
    return record.version === INTEGRATION_PROTOCOL_VERSION
        && typeof record.id === 'string'
        && typeof record.type === 'string'
        && typeof record.source === 'string'
        && typeof record.timestamp === 'number'
        && 'payload' in record;
}
export function assertTrustedMessage(event, allowedOrigin) {
    return event.origin === allowedOrigin && isIntegrationEnvelope(event.data);
}
