import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from 'node:crypto';

const ALGORITHM = 'aes-256-gcm';
const KEY_BYTES = 32;
const IV_BYTES = 12;
const TAG_BYTES = 16;
const HKDF_SALT = 'mcp-oauth:refresh-successor';

// The key is derived from the plaintext refresh token the client presents. The store only holds
// its HMAC, so a database read alone cannot open the successor; only a holder of the token can.
function deriveKey(refreshToken: string): Buffer {
  return Buffer.from(hkdfSync('sha256', refreshToken, HKDF_SALT, '', KEY_BYTES));
}

export function sealSuccessor(refreshToken: string, successor: unknown): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGORITHM, deriveKey(refreshToken), iv);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(successor), 'utf8'),
    cipher.final(),
  ]);
  return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString('base64url');
}

export function openSuccessor<T>(refreshToken: string, sealed: string): T | undefined {
  const payload = Buffer.from(sealed, 'base64url');
  if (payload.length < IV_BYTES + TAG_BYTES) {
    return undefined;
  }
  const iv = payload.subarray(0, IV_BYTES);
  const tag = payload.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
  const ciphertext = payload.subarray(IV_BYTES + TAG_BYTES);
  try {
    const decipher = createDecipheriv(ALGORITHM, deriveKey(refreshToken), iv);
    decipher.setAuthTag(tag);
    const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    return JSON.parse(plaintext.toString('utf8')) as T;
  } catch {
    return undefined;
  }
}
