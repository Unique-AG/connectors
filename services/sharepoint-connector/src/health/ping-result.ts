export type PingResult = { reachable: true } | { reachable: false; errorCode: string };

export function extractErrorCode(error: unknown): string {
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return 'TIMEOUT';
  }
  // undici wraps transport failures in a TypeError whose `.cause` holds the original
  // system error (ECONNREFUSED, ENOTFOUND, ENETUNREACH, etc.) as a NodeJS.ErrnoException.
  const errno = error as NodeJS.ErrnoException;
  const cause = errno.cause as NodeJS.ErrnoException | undefined;
  return errno.code ?? cause?.code ?? 'UNKNOWN';
}
