export const CHANNEL = 'agentic-onlyoffice-v1';

export function validCommand(message) {
  if (!message || typeof message !== 'object') return false;
  if (!Number.isSafeInteger(message.id) || message.id < 1) return false;
  if (['start', 'end', 'advance', 'pause', 'resume'].includes(message.command)) return true;
  return (
    message.command === 'goto' &&
    Number.isSafeInteger(message.page) &&
    message.page >= 1 &&
    message.page <= 5
  );
}

export function validPeerMessage(event, origin, nonce, peer) {
  return (
    Boolean(event.source) &&
    event.origin === origin &&
    (!peer || event.source === peer) &&
    event.data?.channel === CHANNEL &&
    event.data?.nonce === nonce
  );
}
