import { type IntegrationEnvelope, type IntegrationSource } from './messages.js';
export declare function createIntegrationMessage<TType extends string, TPayload>(source: IntegrationSource, type: TType, payload: TPayload): IntegrationEnvelope<TType, TPayload>;
export declare function postIntegrationMessage<TType extends string, TPayload>(target: Window, targetOrigin: string, source: IntegrationSource, type: TType, payload: TPayload): void;
