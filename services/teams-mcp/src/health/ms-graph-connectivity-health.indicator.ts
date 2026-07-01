import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { HealthConfig, healthConfig } from '~/config';
import { extractErrorCode, type PingResult } from './ping-result';

const GRAPH_URL = 'https://graph.microsoft.com/v1.0/';

@Injectable()
export class MsGraphConnectivityHealthIndicator {
  private readonly timeoutMs: number;

  public constructor(
    @Inject(healthConfig.KEY) config: HealthConfig,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.timeoutMs = config.connectivityTimeoutMs;
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    const result = await this.ping(GRAPH_URL);

    if (!result.reachable) {
      return indicator.down({ graph: 'unreachable', graphError: result.errorCode });
    }

    return indicator.up({ graph: 'reachable' });
  }

  private async ping(url: string): Promise<PingResult> {
    try {
      // Node's global fetch is undici under the hood, so transport failures surface the same
      // TypeError/`.cause` shape that `extractErrorCode` unwraps.
      const response = await fetch(url, {
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      // Discard the body so the socket is released instead of held until GC.
      await response.body?.cancel();
      // Any HTTP response (including 401 from unauthenticated requests) is treated as
      // reachable — we're testing network path, not authentication.
      return { reachable: true };
    } catch (error) {
      return { reachable: false, errorCode: extractErrorCode(error) };
    }
  }
}
