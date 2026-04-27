import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { Dispatcher, fetch as undiciFetch } from 'undici';
import { type HealthConfigNamespaced, UniqueAuthMode } from '../config';
import { ProxyService } from '../proxy';
import { ServiceRegistry, type TenantContext, TenantRegistry } from '../tenant';
import { extractErrorCode, type PingResult } from './ping-result';

/**
 * Checks reachability of every tenant's Unique API GraphQL endpoints (ingestion and scope
 * management) by sending a minimal `{ __typename }` query.
 *
 * Each tenant has its own Unique API config, so we ping per tenant rather than per URL — this
 * surfaces auth or routing issues that affect a subset of tenants.
 *
 * Uses direct HTTP requests via `undici` fetch, bypassing the per-tenant `UniqueGraphqlClient`
 * rate limiter (Bottleneck) so health checks are never queued behind sync traffic. Auth headers
 * come from each tenant's existing `UniqueApiClient.auth.getToken()` (or the static cluster_local
 * headers) so we do not duplicate token handling here.
 */
@Injectable()
export class UniqueApiHealthIndicator {
  private readonly timeoutMs: number;

  public constructor(
    configService: ConfigService<HealthConfigNamespaced, true>,
    private readonly proxyService: ProxyService,
    private readonly tenantRegistry: TenantRegistry,
    private readonly serviceRegistry: ServiceRegistry,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = configService.get('health.connectivityTimeoutMs', { infer: true });
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const tenants = this.tenantRegistry.getAllTenants();

    const tenantResults = await Promise.all(tenants.map((tenant) => this.checkTenant(tenant)));

    const ingestion = tenantResults.map((r) => formatEntry(r.tenantName, r.ingestion));
    const scopeManagement = tenantResults.map((r) => formatEntry(r.tenantName, r.scopeManagement));

    const isUp = tenantResults.every((r) => r.ingestion.reachable && r.scopeManagement.reachable);

    const details: Record<string, unknown> = { ingestion, scopeManagement };

    if (!isUp) {
      return indicator.down(details);
    }

    return indicator.up(details);
  }

  private async checkTenant(tenant: TenantContext): Promise<TenantCheckResult> {
    const uniqueConfig = tenant.config.unique;
    const isExternal = uniqueConfig.serviceAuthMode === UniqueAuthMode.External;
    // Match the per-tenant Unique client's routing: cluster_local bypasses the proxy, external
    // goes through it. Health pings must follow the same path so they reflect what the connector
    // actually does in production.
    const dispatcher = this.proxyService.getDispatcher({ mode: isExternal ? 'always' : 'never' });

    let authHeaders: Record<string, string>;
    try {
      authHeaders = await this.tenantRegistry.run(tenant, () =>
        this.buildAuthHeaders(uniqueConfig),
      );
    } catch {
      return {
        tenantName: tenant.name,
        ingestion: { reachable: false, errorCode: 'AUTH_FAILURE' },
        scopeManagement: { reachable: false, errorCode: 'AUTH_FAILURE' },
      };
    }

    const ingestionUrl = `${uniqueConfig.ingestionServiceBaseUrl}/graphql`;
    const scopeManagementUrl = `${uniqueConfig.scopeManagementServiceBaseUrl}/graphql`;

    const [ingestion, scopeManagement] = await Promise.all([
      this.ping(ingestionUrl, authHeaders, dispatcher),
      this.ping(scopeManagementUrl, authHeaders, dispatcher),
    ]);

    return { tenantName: tenant.name, ingestion, scopeManagement };
  }

  private async buildAuthHeaders(
    uniqueConfig: TenantContext['config']['unique'],
  ): Promise<Record<string, string>> {
    if (uniqueConfig.serviceAuthMode === UniqueAuthMode.ClusterLocal) {
      return {
        'x-service-id': 'confluence-connector',
        ...uniqueConfig.serviceExtraHeaders,
      };
    }
    const client = this.serviceRegistry.getService(UniqueApiClient);
    const token = await client.auth.getToken();
    return { Authorization: `Bearer ${token}` };
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
      // Discard the body so undici releases the socket instead of holding it until GC.
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

interface TenantCheckResult {
  tenantName: string;
  ingestion: PingResult;
  scopeManagement: PingResult;
}

function formatEntry(tenantName: string, result: PingResult): Record<string, string> {
  const entry: Record<string, string> = {
    tenant: tenantName,
    status: result.reachable ? 'reachable' : 'unreachable',
  };
  if (!result.reachable) {
    entry.error = result.errorCode;
  }
  return entry;
}
