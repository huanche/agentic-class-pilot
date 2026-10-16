export const TTS_ACCOUNT_ERROR_CODE = 'TTS_PROVIDER_ACCOUNT_UNAVAILABLE' as const;

/** Account failures need operator action; retrying another paragraph cannot fix them. */
export class TTSProviderAccountError extends Error {
  readonly errorCode = TTS_ACCOUNT_ERROR_CODE;
  readonly isRetryable = false;
  constructor(readonly statusCode: 402 | 403) {
    super(
      statusCode === 402
        ? '配音服务账户欠费或余额不足，已暂停生成。请恢复配音服务后重试，已完成页面保留。'
        : '配音服务密钥或访问权限不可用，已暂停生成。请检查服务配置后重试，已完成页面保留。',
    );
    this.name = 'TTSProviderAccountError';
  }
}

export function isTTSProviderAccountError(error: unknown): error is TTSProviderAccountError {
  return (
    error instanceof Error &&
    'errorCode' in error &&
    error.errorCode === TTS_ACCOUNT_ERROR_CODE &&
    'statusCode' in error &&
    (error.statusCode === 402 || error.statusCode === 403)
  );
}

export function throwIfQwenAccountUnavailable(code: unknown, status?: number): void {
  if (code === 'Arrearage') throw new TTSProviderAccountError(402);
  if (status === 401 || code === 'InvalidApiKey' || code === 'InvalidApiKey.Format')
    throw new TTSProviderAccountError(403);
}

/** Classify permanent errors from providers that still return untyped errors. */
export function classifyTTSAccountError(error: unknown): TTSProviderAccountError | undefined {
  if (isTTSProviderAccountError(error)) return error;
  const message = error instanceof Error ? error.message : String(error);
  if (
    /\bArrearage\b|\binsufficient_quota\b|\bPaymentRequired\b|overdue.payment|余额不足|欠费/i.test(
      message,
    )
  ) {
    return new TTSProviderAccountError(402);
  }
  if (
    /\bInvalidApiKey\b|\bInvalidAccessKeyId\b|\bAccessDenied\b|\bAccountDisabled\b/i.test(message)
  ) {
    return new TTSProviderAccountError(403);
  }
}
