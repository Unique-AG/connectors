import { Controller, Get } from '@nestjs/common';
import { HealthCheck, HealthCheckService } from '@nestjs/terminus';
import { ConnectivityHealthIndicator } from './connectivity-health.indicator';
import { SyncHealthIndicator } from './sync-health.indicator';
import { UniqueApiHealthIndicator } from './unique-api-health.indicator';

@Controller('health')
export class HealthController {
  public constructor(
    private readonly healthCheckService: HealthCheckService,
    private readonly syncIndicator: SyncHealthIndicator,
    private readonly connectivityIndicator: ConnectivityHealthIndicator,
    private readonly uniqueApiIndicator: UniqueApiHealthIndicator,
  ) {}

  @Get()
  @HealthCheck()
  public check() {
    return this.healthCheckService.check([
      () => this.syncIndicator.check('sync'),
      () => this.connectivityIndicator.check('connectivity'),
      () => this.uniqueApiIndicator.check('uniqueApi'),
    ]);
  }
}
