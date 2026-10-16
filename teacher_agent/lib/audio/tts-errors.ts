/** Account failures need a configuration/billing change; repeating each clip cannot recover. */
export const TTS_ACCOUNT_UNAVAILABLE = 'TTS_ACCOUNT_UNAVAILABLE';

export function ttsAccountFailureMessage(error: unknown): string | undefined {
  const message = error instanceof Error ? error.message : String(error);
  if (
    /\bArrearage\b|\binsufficient_quota\b|\bPaymentRequired\b|overdue.payment|余额不足|欠费/i.test(
      message,
    )
  ) {
    return '配音服务账户余额不足或已欠费，已暂停配音。请恢复配音服务后重试；已生成的课件和讲稿会保留。';
  }
  if (
    /\bInvalidApiKey\b|\bInvalidAccessKeyId\b|\bAccessDenied\b|\bAccountDisabled\b/i.test(message)
  ) {
    return '配音服务凭据或账户权限不可用，已暂停配音。请检查配音配置后重试；已生成的课件和讲稿会保留。';
  }
}

export function isTtsAccountFailure(error: unknown): boolean {
  return Boolean(
    error &&
    typeof error === 'object' &&
    'errorCode' in error &&
    error.errorCode === TTS_ACCOUNT_UNAVAILABLE,
  );
}
