import { type IntegrationEnvelope } from './messages.js';
export declare function isIntegrationEnvelope(value: unknown): value is IntegrationEnvelope;
export declare function assertTrustedMessage(event: MessageEvent, allowedOrigin: string): boolean;
