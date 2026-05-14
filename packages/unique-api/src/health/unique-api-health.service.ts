import type { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { fetch as undiciFetch } from 'undici';
import type { UniqueAuthFacade } from '../auth/unique-auth.facade';
import { extractErrorCode, type PingResult } from './ping-result';

export class UniqueApiHealth {
  private readonly ingestionUrl: string;
  private readonly scopeManagementUrl: string;

  public constructor(
    private readonly auth: UniqueAuthFacade,
    ingestionBaseUrl: string,
    scopeManagementBaseUrl: string,
    private readonly timeoutMs: number,
  ) {
    this.ingestionUrl = `${ingestionBaseUrl}/graphql`;
    this.scopeManagementUrl = `${scopeManagementBaseUrl}/graphql`;
  }

  public async checkIngestion(
    key: string,
    healthIndicatorService: HealthIndicatorService,
  ): Promise<HealthIndicatorResult> {
    const indicator = healthIndicatorService.check(key);
    const result = await this.pingEndpoint(this.ingestionUrl);
    if (!result.reachable) {
      return indicator.down({ ingestion: 'unreachable', ingestionError: result.errorCode });
    }
    return indicator.up({ ingestion: 'reachable' });
  }

  public async checkScopeManagement(
    key: string,
    healthIndicatorService: HealthIndicatorService,
  ): Promise<HealthIndicatorResult> {
    const indicator = healthIndicatorService.check(key);
    const result = await this.pingEndpoint(this.scopeManagementUrl);
    if (!result.reachable) {
      return indicator.down({
        scopeManagement: 'unreachable',
        scopeManagementError: result.errorCode,
      });
    }
    return indicator.up({ scopeManagement: 'reachable' });
  }

  private async pingEndpoint(url: string): Promise<PingResult> {
    let authHeaders: Record<string, string>;
    try {
      authHeaders = await this.auth.getAuthHeaders();
    } catch {
      return { reachable: false, errorCode: 'AUTH_FAILURE' };
    }

    try {
      const response = await undiciFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ query: '{ __typename }' }),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      await response.body?.cancel();
      if (response.ok) {
        return { reachable: true };
      }
      return { reachable: false, errorCode: `HTTP_${response.status}` };
    } catch (error) {
      return { reachable: false, errorCode: extractErrorCode(error) };
    }
  }
}
