import { describe, expect, it } from 'vitest';
import { openSuccessor, sealSuccessor } from './successor-cipher';

describe('successor cipher', () => {
  const pair = { access_token: 'access', refresh_token: 'refresh', expires_in: 3600 };

  it('round-trips a token pair under the redeemed token', () => {
    const sealed = sealSuccessor('redeemed-token', pair);

    expect(sealed).not.toContain('access');
    expect(openSuccessor('redeemed-token', sealed)).toEqual(pair);
  });

  it('produces a different ciphertext for every seal', () => {
    expect(sealSuccessor('redeemed-token', pair)).not.toBe(sealSuccessor('redeemed-token', pair));
  });

  it('cannot be opened with another token', () => {
    const sealed = sealSuccessor('redeemed-token', pair);

    expect(openSuccessor('other-token', sealed)).toBeUndefined();
  });

  it('rejects a tampered payload', () => {
    const sealed = Buffer.from(sealSuccessor('redeemed-token', pair), 'base64url');
    const last = sealed.length - 1;
    sealed.writeUInt8(sealed.readUInt8(last) ^ 0xff, last);

    expect(openSuccessor('redeemed-token', sealed.toString('base64url'))).toBeUndefined();
  });

  it('rejects a payload too short to carry a nonce and tag', () => {
    expect(openSuccessor('redeemed-token', 'abc')).toBeUndefined();
  });
});
