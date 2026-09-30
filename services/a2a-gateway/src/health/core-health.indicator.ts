import { Inject, Injectable } from '@nestjs/common';
import { type HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

@Injectable()
export class CoreHealthIndicator {
  public constructor(
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
    private readonly indicators: HealthIndicatorService,
  ) {}

  public async check(): Promise<HealthIndicatorResult> {
    const indicator = this.indicators.check('unique-core');
    const dependencies = {
      chat: this.config.uniqueChatUrl,
      'scope-management': this.config.uniqueScopeManagementUrl,
      ingestion: this.config.uniqueIngestionUrl,
    };

    try {
      await Promise.all(
        Object.entries(dependencies).map(async ([name, baseUrl]) => {
          const response = await fetch(new URL('/probe', baseUrl), {
            signal: AbortSignal.timeout(this.config.dependencyTimeoutMs),
          });
          if (!response.ok) {
            throw new Error(`${name} health returned ${response.status}`);
          }
        }),
      );
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
