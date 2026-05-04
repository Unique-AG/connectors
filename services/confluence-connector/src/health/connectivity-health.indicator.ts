import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { Dispatcher, fetch as undiciFetch } from 'undici';
import { type HealthConfigNamespaced, TenantStatus } from '../config';
import { ProxyService } from '../proxy';
import { TenantRegistry } from '../tenant';
import { extractErrorCode, type PingResult } from './ping-result';

const ATLASSIAN_API_URL = 'https://api.atlassian.com/';

/**
 * Verifies network-level reachability to the Atlassian API (for Cloud tenants) and to each
 * tenant's configured Confluence base URL.
 *
 * Performs unauthenticated HTTP GET requests — no tokens are acquired. Any HTTP response
 * (including 401/403) proves the endpoint is reachable over the network. Only transport-level
 * failures (DNS, TLS, timeout, connection refused) are treated as unreachable.
 *
 * This separates "can the pod reach the service?" from "are our credentials valid?", so
 * connectivity issues are not masked by auth problems and vice versa.
 */
@Injectable()
export class ConnectivityHealthIndicator {
  private readonly timeoutMs: number;

  public constructor(
    configService: ConfigService<HealthConfigNamespaced, true>,
    private readonly proxyService: ProxyService,
    private readonly tenantRegistry: TenantRegistry,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = configService.get('health.connectivityTimeoutMs', { infer: true });
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const dispatcher: Dispatcher = this.proxyService.getDispatcher({ mode: 'always' });

    // Deleted tenants no longer talk to Confluence — they only run Unique-side cleanup —
    // so excluding them here avoids reporting noise on instances they never reach.
    const tenants = this.tenantRegistry
      .getAllTenants()
      .filter((t) => t.status === TenantStatus.Active);
    const hasCloudTenant = tenants.some((t) => t.config.confluence.instanceType === 'cloud');

    // Deduplicate confluence base URLs so we only ping each host once even when several
    // tenants share an instance.
    const uniqueBaseUrls = new Map<string, string[]>();
    for (const tenant of tenants) {
      const url = tenant.config.confluence.baseUrl;
      const tenantsForUrl = uniqueBaseUrls.get(url) ?? [];
      tenantsForUrl.push(tenant.name);
      uniqueBaseUrls.set(url, tenantsForUrl);
    }

    const atlassianPromise: Promise<PingResult | null> = hasCloudTenant
      ? this.ping(ATLASSIAN_API_URL, dispatcher)
      : Promise.resolve(null);

    const confluencePromises = [...uniqueBaseUrls.entries()].map(async ([baseUrl, tenantNames]) => {
      const result = await this.ping(`${baseUrl}/`, dispatcher);
      return { baseUrl, tenantNames, result };
    });

    const [atlassianResult, confluenceResults] = await Promise.all([
      atlassianPromise,
      Promise.all(confluencePromises),
    ]);

    const details: Record<string, unknown> = {};

    if (atlassianResult) {
      details.atlassian = atlassianResult.reachable ? 'reachable' : 'unreachable';
      if (!atlassianResult.reachable) {
        details.atlassianError = atlassianResult.errorCode;
      }
    }

    const confluenceEntries = confluenceResults.flatMap(({ tenantNames, result }) =>
      tenantNames.map((tenantName) => {
        const entry: Record<string, string> = {
          tenant: tenantName,
          status: result.reachable ? 'reachable' : 'unreachable',
        };
        if (!result.reachable) {
          entry.error = result.errorCode;
        }
        return entry;
      }),
    );

    details.confluence = confluenceEntries;

    const atlassianUp = !atlassianResult || atlassianResult.reachable;
    const confluenceUp = confluenceResults.every(({ result }) => result.reachable);
    const isUp = atlassianUp && confluenceUp;

    if (!isUp) {
      return indicator.down(details);
    }

    return indicator.up(details);
  }

  private async ping(url: string, dispatcher: Dispatcher): Promise<PingResult> {
    try {
      const response = await undiciFetch(url, {
        dispatcher,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      // Discard the body so undici releases the socket instead of holding it until GC.
      await response.body?.cancel();
      return { reachable: true };
    } catch (error) {
      return { reachable: false, errorCode: extractErrorCode(error) };
    }
  }
}
