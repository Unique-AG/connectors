export interface PingResult {
  reachable: boolean;
  errorCode?: string;
}

export function extractErrorCode(error: unknown): string {
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return 'TIMEOUT';
  }
  // undici throws system-level errors (ECONNREFUSED, ENOTFOUND, etc.) as NodeJS.ErrnoException
  // with a `.code` property identifying the OS-level failure reason.
  return (error as NodeJS.ErrnoException).code ?? 'UNKNOWN';
}
