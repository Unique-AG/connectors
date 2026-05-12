import { UniqueApiClient } from '@unique-ag/unique-api';
import { Controller, Get, Inject } from '@nestjs/common';
import {
  HealthCheck,
  HealthCheckService,
  HealthIndicatorResult,
  HealthIndicatorService,
} from '@nestjs/terminus';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { AmqpHealthIndicator } from './amqp-health.indicator';
import { ConnectivityHealthIndicator } from './connectivity-health.indicator';
import { DatabaseHealthIndicator } from './database-health.indicator';
import { McpProcessesHealthIndicator } from './mcp-processes-health.indicator';

@Controller('health')
export class HealthController {
  public constructor(
    private readonly healthCheckService: HealthCheckService,
    private readonly healthIndicatorService: HealthIndicatorService,
    @InjectUniqueApi() private readonly uniqueApiClient: UniqueApiClient,
    private readonly connectivityIndicator: ConnectivityHealthIndicator,
    private readonly databaseIndicator: DatabaseHealthIndicator,
    private readonly amqpIndicator: AmqpHealthIndicator,
    private readonly mcpProcessesIndicator: McpProcessesHealthIndicator,
    @Inject(delegatedAccessConfig.KEY) private delegatedAccessEnvConfig: DelegatedAccessConfig,
  ) {}

  @Get()
  @HealthCheck()
  public check() {
    const checksToRun: (() => Promise<HealthIndicatorResult>)[] = [
      () => this.connectivityIndicator.check('connectivity'),
      () => this.databaseIndicator.check('database'),
      () => this.amqpIndicator.check('amqp'),
    ];

    if (this.delegatedAccessEnvConfig.scan !== 'disabled') {
      checksToRun.push(() =>
        this.mcpProcessesIndicator.checkDelegatedAccess('mcpProcesses.delegatedAccess'),
      );
    }

    if (isMicrosoftGraphBackend()) {
      return this.healthCheckService.check(checksToRun);
    }
    return this.healthCheckService.check([
      ...checksToRun,
      () =>
        this.uniqueApiClient.health.checkIngestion(
          'uniqueApi.ingestion',
          this.healthIndicatorService,
        ),
      () =>
        this.uniqueApiClient.health.checkScopeManagement(
          'uniqueApi.scopeManagement',
          this.healthIndicatorService,
        ),
      () => this.mcpProcessesIndicator.checkFullSync('mcpProcesses.fullSync'),
      () => this.mcpProcessesIndicator.checkLiveCatchup('mcpProcesses.liveCatchup'),
    ]);
  }
}
