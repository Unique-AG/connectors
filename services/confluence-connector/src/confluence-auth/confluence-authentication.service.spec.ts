import { describe, expect, it, vi } from 'vitest';
import { ConfluenceAuthenticationService } from './confluence-authentication.service';
import type {
  ConfluenceAuthStrategy,
  TokenResult,
} from './strategies/confluence-auth-strategy.interface';

function createMockStrategy(result: TokenResult): ConfluenceAuthStrategy {
  return { acquireToken: vi.fn<() => Promise<TokenResult>>().mockResolvedValue(result) };
}

describe('ConfluenceAuthenticationService', () => {
  it('delegates to the injected strategy and returns the access token', async () => {
    const strategy = createMockStrategy({
      accessToken: 'oauth-token-123',
      expiresAt: new Date(Date.now() + 3600 * 1000),
    });

    const service = new ConfluenceAuthenticationService(strategy);
    const token = await service.getAccessToken();

    expect(token).toBe('oauth-token-123');
    expect(strategy.acquireToken).toHaveBeenCalledOnce();
  });

  it('caches the token on subsequent calls', async () => {
    const strategy = createMockStrategy({
      accessToken: 'oauth-token-123',
      expiresAt: new Date(Date.now() + 3600 * 1000),
    });

    const service = new ConfluenceAuthenticationService(strategy);

    await service.getAccessToken();
    await service.getAccessToken();

    expect(strategy.acquireToken).toHaveBeenCalledOnce();
  });

  it('works with PAT tokens that have no expiry', async () => {
    const strategy = createMockStrategy({ accessToken: 'pat-token' });

    const service = new ConfluenceAuthenticationService(strategy);
    const token = await service.getAccessToken();

    expect(token).toBe('pat-token');
  });

  it('retries acquisition after a failure', async () => {
    const strategy: ConfluenceAuthStrategy = {
      acquireToken: vi
        .fn<() => Promise<TokenResult>>()
        .mockRejectedValueOnce(new Error('network error'))
        .mockResolvedValueOnce({
          accessToken: 'recovered-token',
          expiresAt: new Date(Date.now() + 3600 * 1000),
        }),
    };

    const service = new ConfluenceAuthenticationService(strategy);

    await expect(service.getAccessToken()).rejects.toThrow('network error');

    const token = await service.getAccessToken();
    expect(token).toBe('recovered-token');
  });
});
