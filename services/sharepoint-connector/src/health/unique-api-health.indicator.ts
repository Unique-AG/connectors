import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { Dispatcher, fetch as undiciFetch } from 'undici';
import { Config } from '../config';
import { ProxyService } from '../proxy/proxy.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';

interface PingResult {
  reachable: boolean;
  errorCode?: string;
}

/**
 * Checks reachability of both Unique API GraphQL endpoints (ingestion and scope management)
 * by sending a minimal `{ __typename }` query.
 *
 * Uses direct HTTP requests via `undici` fetch, bypassing the `UniqueGraphqlClient` rate limiter
 * (Bottleneck) so health checks are never queued behind sync traffic.
 */
@Injectable()
export class UniqueApiHealthIndicator {
  private readonly timeoutMs: number;
  private readonly ingestionUrl: string;
  private readonly scopeManagementUrl: string;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly proxyService: ProxyService,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = configService.get('health.connectivityTimeoutMs', { infer: true });
    this.ingestionUrl = `${configService.get('unique.ingestionServiceBaseUrl', { infer: true })}/graphql`;
    this.scopeManagementUrl = `${configService.get('unique.scopeManagementServiceBaseUrl', { infer: true })}/graphql`;
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const dispatcher = this.proxyService.getDispatcher({ mode: 'for-external-only' });
    const authHeaders = await this.getAuthHeaders();

    const [ingestionResult, scopeManagementResult] = await Promise.all([
      this.ping(this.ingestionUrl, authHeaders, dispatcher),
      this.ping(this.scopeManagementUrl, authHeaders, dispatcher),
    ]);

    const details: Record<string, string> = {};

    details.ingestion = ingestionResult.reachable ? 'reachable' : 'unreachable';
    if (ingestionResult.errorCode) {
      details.ingestionError = ingestionResult.errorCode;
    }

    details.scopeManagement = scopeManagementResult.reachable ? 'reachable' : 'unreachable';
    if (scopeManagementResult.errorCode) {
      details.scopeManagementError = scopeManagementResult.errorCode;
    }

    const isUp = ingestionResult.reachable && scopeManagementResult.reachable;

    if (!isUp) {
      return indicator.down(details);
    }

    return indicator.up(details);
  }

  private async getAuthHeaders(): Promise<Record<string, string>> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    return uniqueConfig.serviceAuthMode === 'cluster_local'
      ? { 'x-service-id': 'sharepoint-connector', ...uniqueConfig.serviceExtraHeaders }
      : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };
  }

  private async ping(
    url: string,
    authHeaders: Record<string, string>,
    dispatcher: Dispatcher,
  ): Promise<PingResult> {
    try {
      const response = await undiciFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ query: '{ __typename }' }),
        dispatcher,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (response.ok) {
        return { reachable: true };
      }
      return { reachable: false, errorCode: `HTTP_${response.status}` };
    } catch (error) {
      return { reachable: false, errorCode: (error as NodeJS.ErrnoException).code ?? 'UNKNOWN' };
    }
  }
}
