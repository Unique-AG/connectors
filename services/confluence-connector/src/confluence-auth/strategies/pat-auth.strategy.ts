import { AuthMode } from '../../config/confluence.schema';
import type { Redacted } from '../../utils/redacted';
import type { ConfluenceAuthStrategy, TokenResult } from './confluence-auth-strategy.interface';

interface PatAuthConfig {
  mode: typeof AuthMode.PAT;
  token: Redacted<string>;
}

export class PatAuthStrategy implements ConfluenceAuthStrategy {
  private readonly token: string;

  public constructor(authConfig: PatAuthConfig) {
    this.token = authConfig.token.value;
  }

  public async acquireToken(): Promise<TokenResult> {
    return { accessToken: this.token };
  }
}
