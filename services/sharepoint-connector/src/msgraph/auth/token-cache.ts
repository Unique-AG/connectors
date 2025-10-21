export interface TokenAcquisitionResult {
  token: string;
  expiresAt: number;
}

export class TokenCache {
  // We keep the promise and cached value separately to avoid race condition when the token expires.
  //    With cached value we're sure that within the script execution we either have a valid token
  //    or request new one and populate promise cache. It is more problematic with just the promise,
  //    because we have to await it to check if token didn't expire, yielding control and possibly
  //    introduce race condition.
  private cachedToken: TokenAcquisitionResult | null = null;
  private tokenPromise: Promise<string> | null = null;
  private readonly bufferTimeMs: number;

  public constructor(bufferTimeMs = 5 * 60 * 1000) {
    this.bufferTimeMs = bufferTimeMs;
  }

  public async getToken(acquireToken: () => Promise<TokenAcquisitionResult>): Promise<string> {
    if (this.cachedToken && this.isTokenValid(this.cachedToken)) {
      return this.cachedToken.token;
    }

    if (this.tokenPromise) {
      return this.tokenPromise;
    }

    this.tokenPromise = this.acquireAndCache(acquireToken).finally(() => {
      this.tokenPromise = null;
    });

    return this.tokenPromise;
  }

  private async acquireAndCache(
    acquireToken: () => Promise<TokenAcquisitionResult>,
  ): Promise<string> {
    try {
      this.cachedToken = await acquireToken();
      return this.cachedToken.token;
    } catch (error) {
      this.cachedToken = null;
      throw error;
    }
  }

  private isTokenValid(token: TokenAcquisitionResult): boolean {
    return token.expiresAt > Date.now() + this.bufferTimeMs;
  }
}
