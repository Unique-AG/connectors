import { DEFAULT_TOKEN_EXPIRATION_BUFFER_MS } from '../constants/defaults.constants';

export function isTokenExpiringSoon(
  expiresOn: Date | number | null | undefined,
  bufferMs: number = DEFAULT_TOKEN_EXPIRATION_BUFFER_MS,
): boolean {
  if (!expiresOn) {
    return true;
  }

  const expirationTime = expiresOn instanceof Date ? expiresOn.getTime() : expiresOn;
  return expirationTime <= Date.now() + bufferMs;
}
