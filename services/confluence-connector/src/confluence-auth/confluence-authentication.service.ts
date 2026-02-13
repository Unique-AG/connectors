import { Inject, Injectable } from '@nestjs/common';
import { CONFLUENCE_AUTH_STRATEGY } from './confluence-auth.constants';
import type { ConfluenceAuthStrategy } from './strategies/confluence-auth-strategy.interface';
import { TokenCache } from './token-cache';

@Injectable()
export class ConfluenceAuthenticationService {
  private readonly tokenCache = new TokenCache();

  public constructor(
    @Inject(CONFLUENCE_AUTH_STRATEGY)
    private readonly strategy: ConfluenceAuthStrategy,
  ) {}

  public async getAccessToken(): Promise<string> {
    return this.tokenCache.getToken(() => this.strategy.acquireToken());
  }
}
