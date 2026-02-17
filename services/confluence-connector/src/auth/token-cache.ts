import type { TokenResult } from './confluence-auth/strategies/confluence-auth-strategy.interface';

const DEFAULT_BUFFER_MS = 5 * 60 * 1000;

export class TokenCache {
  // Cached value and in-flight promise are kept separately to avoid race conditions.
  private cachedToken: TokenResult | null = null;
  private tokenPromise: Promise<string> | null = null;
  private readonly bufferTimeMs: number;

  public constructor(bufferTimeMs = DEFAULT_BUFFER_MS) {
    this.bufferTimeMs = bufferTimeMs;
  }

  public async getToken(acquireToken: () => Promise<TokenResult>): Promise<string> {
    if (this.cachedToken && this.isTokenValid(this.cachedToken)) {
      return this.cachedToken.accessToken;
    }

    if (this.tokenPromise) {
      return this.tokenPromise;
    }

    this.tokenPromise = this.acquireAndCache(acquireToken).finally(() => {
      this.tokenPromise = null;
    });

    return this.tokenPromise;
  }

  private async acquireAndCache(acquireToken: () => Promise<TokenResult>): Promise<string> {
    try {
      this.cachedToken = await acquireToken();
      return this.cachedToken.accessToken;
    } catch (error) {
      this.cachedToken = null;
      throw error;
    }
  }

  private isTokenValid(token: TokenResult): boolean {
    if (!token.expiresAt) return true;
    return token.expiresAt.getTime() > Date.now() + this.bufferTimeMs;
  }
}
