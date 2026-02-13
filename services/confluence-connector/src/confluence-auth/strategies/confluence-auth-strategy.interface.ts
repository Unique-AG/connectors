export interface TokenResult {
  accessToken: string;
  expiresAt?: Date;
}

export interface ConfluenceAuthStrategy {
  acquireToken(): Promise<TokenResult>;
}
