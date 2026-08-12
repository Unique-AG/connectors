import { ProxyService } from '@unique-ag/proxy';
import { extractErrorCode, type PingResult } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { Dispatcher, fetch as undiciFetch } from 'undici';
import { IngestionConfig, ingestionConfig } from '~/config';

const GRAPH_URL = 'https://graph.microsoft.com/v1.0/';

@Injectable()
export class MsGraphConnectivityHealthIndicator {
  private readonly timeoutMs: number;

  public constructor(
    @Inject(ingestionConfig.KEY) config: IngestionConfig,
    private readonly proxyService: ProxyService,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = config.connectivityTimeoutMs;
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const dispatcher: Dispatcher = this.proxyService.getDispatcher({ mode: 'always' });
    const result = await this.ping(GRAPH_URL, dispatcher);

    if (!result.reachable) {
      return indicator.down({ graph: 'unreachable', graphError: result.errorCode });
    }

    return indicator.up({ graph: 'reachable' });
  }

  private async ping(url: string, dispatcher: Dispatcher): Promise<PingResult> {
    try {
      const response = await undiciFetch(url, {
        dispatcher,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      await response.body?.cancel();
      // Any HTTP response (including 401 from unauthenticated requests) is treated as
      // reachable — we're testing network path, not authentication.
      return { reachable: true };
    } catch (error) {
      return { reachable: false, errorCode: extractErrorCode(error) };
    }
  }
}
