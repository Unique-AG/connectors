import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TokenResult } from './strategies/confluence-auth-strategy.interface';
import { TokenCache } from './token-cache';

describe('TokenCache', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-02-13T12:00:00.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('cache miss', () => {
    it('acquires a token on first call', async () => {
      const cache = new TokenCache();
      const acquire = vi.fn<() => Promise<TokenResult>>().mockResolvedValue({
        accessToken: 'token-1',
        expiresAt: new Date('2026-02-13T13:00:00.000Z'),
      });

      const token = await cache.getToken(acquire);

      expect(token).toBe('token-1');
      expect(acquire).toHaveBeenCalledOnce();
    });
  });

  describe('cache hit', () => {
    it('returns cached token without re-acquiring', async () => {
      const cache = new TokenCache();
      const acquire = vi.fn<() => Promise<TokenResult>>().mockResolvedValue({
        accessToken: 'token-1',
        expiresAt: new Date('2026-02-13T13:00:00.000Z'),
      });

      await cache.getToken(acquire);
      const token = await cache.getToken(acquire);

      expect(token).toBe('token-1');
      expect(acquire).toHaveBeenCalledOnce();
    });
  });

  describe('expiry buffer', () => {
    it('re-acquires when token is within the buffer window', async () => {
      const cache = new TokenCache(5 * 60 * 1000);
      const acquire = vi
        .fn<() => Promise<TokenResult>>()
        .mockResolvedValueOnce({
          accessToken: 'token-1',
          expiresAt: new Date('2026-02-13T13:00:00.000Z'),
        })
        .mockResolvedValueOnce({
          accessToken: 'token-2',
          expiresAt: new Date('2026-02-13T14:00:00.000Z'),
        });

      await cache.getToken(acquire);

      // Advance to 4 minutes before expiry (within 5-min buffer)
      vi.setSystemTime(new Date('2026-02-13T12:56:00.000Z'));

      const token = await cache.getToken(acquire);

      expect(token).toBe('token-2');
      expect(acquire).toHaveBeenCalledTimes(2);
    });

    it('keeps cached token when still outside the buffer window', async () => {
      const cache = new TokenCache(5 * 60 * 1000);
      const acquire = vi.fn<() => Promise<TokenResult>>().mockResolvedValue({
        accessToken: 'token-1',
        expiresAt: new Date('2026-02-13T13:00:00.000Z'),
      });

      await cache.getToken(acquire);

      // Advance to 6 minutes before expiry (outside 5-min buffer)
      vi.setSystemTime(new Date('2026-02-13T12:54:00.000Z'));

      const token = await cache.getToken(acquire);

      expect(token).toBe('token-1');
      expect(acquire).toHaveBeenCalledOnce();
    });
  });

  describe('PAT tokens (no expiry)', () => {
    it('caches indefinitely when expiresAt is undefined', async () => {
      const cache = new TokenCache();
      const acquire = vi.fn<() => Promise<TokenResult>>().mockResolvedValue({
        accessToken: 'pat-token',
      });

      await cache.getToken(acquire);

      // Advance time significantly
      vi.setSystemTime(new Date('2027-01-01T00:00:00.000Z'));

      const token = await cache.getToken(acquire);

      expect(token).toBe('pat-token');
      expect(acquire).toHaveBeenCalledOnce();
    });
  });

  describe('promise deduplication', () => {
    it('shares a single acquisition across concurrent calls', async () => {
      const cache = new TokenCache();
      const acquire = vi.fn<() => Promise<TokenResult>>().mockResolvedValue({
        accessToken: 'token-1',
        expiresAt: new Date('2026-02-13T13:00:00.000Z'),
      });

      const [t1, t2, t3] = await Promise.all([
        cache.getToken(acquire),
        cache.getToken(acquire),
        cache.getToken(acquire),
      ]);

      expect(t1).toBe('token-1');
      expect(t2).toBe('token-1');
      expect(t3).toBe('token-1');
      expect(acquire).toHaveBeenCalledOnce();
    });
  });

  describe('failure invalidation', () => {
    it('clears cache on acquisition failure and retries on next call', async () => {
      const cache = new TokenCache();
      const acquire = vi
        .fn<() => Promise<TokenResult>>()
        .mockRejectedValueOnce(new Error('network error'))
        .mockResolvedValueOnce({
          accessToken: 'token-after-retry',
          expiresAt: new Date('2026-02-13T13:00:00.000Z'),
        });

      await expect(cache.getToken(acquire)).rejects.toThrow('network error');

      const token = await cache.getToken(acquire);

      expect(token).toBe('token-after-retry');
      expect(acquire).toHaveBeenCalledTimes(2);
    });

    it('does not cache a failed acquisition', async () => {
      const cache = new TokenCache();
      const acquire = vi
        .fn<() => Promise<TokenResult>>()
        .mockRejectedValueOnce(new Error('fail-1'))
        .mockRejectedValueOnce(new Error('fail-2'));

      await expect(cache.getToken(acquire)).rejects.toThrow('fail-1');
      await expect(cache.getToken(acquire)).rejects.toThrow('fail-2');

      expect(acquire).toHaveBeenCalledTimes(2);
    });
  });
});
