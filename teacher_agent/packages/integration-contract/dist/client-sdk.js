import { INTEGRATION_PROTOCOL_VERSION, } from './messages.js';
function messageId() {
    return globalThis.crypto?.randomUUID?.() ?? `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
export function createIntegrationMessage(source, type, payload) {
    return {
        version: INTEGRATION_PROTOCOL_VERSION,
        id: messageId(),
        type,
        source,
        timestamp: Date.now(),
        payload,
    };
}
export function postIntegrationMessage(target, targetOrigin, source, type, payload) {
    if (!targetOrigin || targetOrigin === '*')
        throw new Error('A concrete targetOrigin is required');
    target.postMessage(createIntegrationMessage(source, type, payload), targetOrigin);
}
