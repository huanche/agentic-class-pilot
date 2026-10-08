/** Platform login/permission failures are not model credential failures. */
export function isModelCredentialFailure(failure: {
  errorCode?: string;
  statusCode?: number;
}): boolean {
  return failure.errorCode === 'MISSING_API_KEY' ||
    (failure.errorCode === 'UPSTREAM_ERROR' &&
      (failure.statusCode === 401 || failure.statusCode === 403));
}
