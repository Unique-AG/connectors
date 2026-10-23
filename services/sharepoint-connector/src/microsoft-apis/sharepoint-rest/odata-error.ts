import { isPlainObject } from 'remeda';

// Only the code is read, never the message, because the message can contain list or file names.
export function extractODataErrorCode(payload: unknown): string | undefined {
  if (!isPlainObject(payload) || !isPlainObject(payload['odata.error'])) {
    return undefined;
  }
  const { code } = payload['odata.error'];
  return typeof code === 'string' ? code : undefined;
}
