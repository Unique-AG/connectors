import { Controller, Get, Inject } from '@nestjs/common';
import { HealthCheck, HealthCheckService, MemoryHealthIndicator } from '@nestjs/terminus';
import { type HealthConfig, healthConfig as healthConfigProvider } from './health.config';
import { VersionHealthIndicator } from './version-health.service';

@Controller('health')
export class HealthController {
  public constructor(
    @Inject(healthConfigProvider.KEY)
    private readonly healthConfig: HealthConfig,
    private readonly health: HealthCheckService,
    private readonly memory: MemoryHealthIndicator,
    private readonly version: VersionHealthIndicator,
  ) {}

  @Get()
  @HealthCheck()
  public check() {
    return this.health.check([
      () => this.memory.checkHeap('memory_heap', this.healthConfig.maxHeapMb * 1024 * 1024),
      () => this.version.check(),
    ]);
  }
}
