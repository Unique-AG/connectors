export interface TokenAcquisitionResult {
  token: string;
  expiresAt: number;
}

export class TokenCache {
  private tokenCachePromise: Promise<TokenAcquisitionResult> | null = null;
  private readonly bufferTimeMs: number;

  public constructor(bufferTimeMs = 5 * 60 * 1000) {
    this.bufferTimeMs = bufferTimeMs;
  }

  public async getToken(acquireToken: () => Promise<TokenAcquisitionResult>): Promise<string> {
    if (!this.tokenCachePromise) {
      this.tokenCachePromise = acquireToken();
    }

    let cachedToken = await this.tokenCachePromise;

    if (!this.isTokenValid(cachedToken)) {
      this.tokenCachePromise = acquireToken();
      cachedToken = await this.tokenCachePromise;
    }

    return cachedToken.token;
  }

  private isTokenValid(token: TokenAcquisitionResult): boolean {
    return token.expiresAt > Date.now() + this.bufferTimeMs;
  }
}
