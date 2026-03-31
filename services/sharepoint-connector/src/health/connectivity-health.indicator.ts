import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { fetch as undiciFetch, Dispatcher } from 'undici';

import { Config } from '../config';
import { ProxyService } from '../proxy/proxy.service';

const GRAPH_URL = 'https://graph.microsoft.com/v1.0/';

interface PingResult {
  reachable: boolean;
  errorCode?: string;
}

/**
 * Verifies network-level reachability to Microsoft Graph and SharePoint REST APIs.
 *
 * Performs unauthenticated HTTP GET requests — no tokens are acquired. Any HTTP response
 * (including 401/403) proves the endpoint is reachable over the network. Only transport-level
 * failures (DNS, TLS, timeout, connection refused) are treated as unreachable.
 *
 * This separates "can the pod reach the service?" from "are our credentials valid?", so
 * connectivity issues are not masked by auth problems and vice versa.
 *
 * SharePoint results use a per-tenant array (currently always `"default"`) to support
 * future multi-tenancy without breaking the response contract. URLs are omitted from the
 * response as they are considered sensitive.
 */
@Injectable()
export class ConnectivityHealthIndicator {
  private readonly timeoutMs: number;
  private readonly sharepointBaseUrl: string;

  constructor(
    configService: ConfigService<Config, true>,
    private readonly proxyService: ProxyService,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = configService.get('health.connectivityTimeoutMs', { infer: true });
    this.sharepointBaseUrl = configService.get('sharepoint.baseUrl', { infer: true });
  }

  async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const dispatcher: Dispatcher = this.proxyService.getDispatcher({ mode: 'always' });

    const [graphResult, sharepointResult] = await Promise.all([
      this.ping(GRAPH_URL, dispatcher),
      this.ping(`${this.sharepointBaseUrl}/`, dispatcher),
    ]);

    const details: Record<string, unknown> = {
      graph: graphResult.reachable ? 'reachable' : 'unreachable',
    };

    if (!graphResult.reachable) {
      details.graphError = graphResult.errorCode;
    }

    const sharepointEntry: Record<string, string> = {
      tenant: 'default',
      status: sharepointResult.reachable ? 'reachable' : 'unreachable',
    };

    if (sharepointResult.errorCode) {
      sharepointEntry.error = sharepointResult.errorCode;
    }

    details.sharepoint = [sharepointEntry];

    const isUp = graphResult.reachable && sharepointResult.reachable;

    if (!isUp) {
      return indicator.down(details);
    }

    return indicator.up(details);
  }

  private async ping(url: string, dispatcher: Dispatcher): Promise<PingResult> {
    try {
      await undiciFetch(url, {
        dispatcher,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      return { reachable: true };
    } catch (error) {
      return {
        reachable: false,
        errorCode: (error as NodeJS.ErrnoException).code ?? 'UNKNOWN',
      };
    }
  }
}
