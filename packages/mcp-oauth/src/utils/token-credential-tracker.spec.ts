import type { ExecutionContext } from '@nestjs/common';
import { describe, expect, it } from 'vitest';
import { tokenCredentialTracker } from './token-credential-tracker';

const context = {} as ExecutionContext;
const ip = '203.0.113.10';

describe('tokenCredentialTracker', () => {
  it('gives two refresh tokens from one IP separate buckets', async () => {
    const first = await tokenCredentialTracker({ ip, body: { refresh_token: 'rt-1' } }, context);
    const second = await tokenCredentialTracker({ ip, body: { refresh_token: 'rt-2' } }, context);

    expect(first).not.toBe(second);
    expect(first.startsWith(`${ip}:`)).toBe(true);
    expect(second.startsWith(`${ip}:`)).toBe(true);
  });

  it('gives the same credential from one IP the same bucket', async () => {
    const first = await tokenCredentialTracker({ ip, body: { code: 'code-1' } }, context);
    const second = await tokenCredentialTracker({ ip, body: { code: 'code-1' } }, context);

    expect(first).toBe(second);
  });

  it('separates the same credential presented from two IPs', async () => {
    const first = await tokenCredentialTracker({ ip, body: { code: 'code-1' } }, context);
    const second = await tokenCredentialTracker(
      { ip: '198.51.100.7', body: { code: 'code-1' } },
      context,
    );

    expect(first).not.toBe(second);
  });

  it('never puts the credential itself in the tracker', async () => {
    const tracker = await tokenCredentialTracker({ ip, body: { refresh_token: 'rt-1' } }, context);

    expect(tracker).not.toContain('rt-1');
  });

  it('shares one bucket per IP for requests without a credential', async () => {
    const noBody = await tokenCredentialTracker({ ip }, context);
    const emptyBody = await tokenCredentialTracker({ ip, body: {} }, context);
    const wrongType = await tokenCredentialTracker({ ip, body: { code: 42 } }, context);

    expect(noBody).toBe(emptyBody);
    expect(noBody).toBe(wrongType);
  });
});
