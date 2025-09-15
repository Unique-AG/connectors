import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorService } from '@nestjs/terminus';
import { type HealthConfig, healthConfig as healthConfigProvider } from './health.config';

@Injectable()
export class VersionHealthIndicator {
  public constructor(
    @Inject(healthConfigProvider.KEY)
    private readonly healthConfig: HealthConfig,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {}

  public check() {
    const indicator = this.healthIndicatorService.check('version');

    return indicator.up({ version: this.healthConfig.version });
  }
}
