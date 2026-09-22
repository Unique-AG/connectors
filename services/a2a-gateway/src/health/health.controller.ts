import { Controller, Get } from '@nestjs/common';
import { HealthCheck, HealthCheckService } from '@nestjs/terminus';
import { AmqpHealthIndicator } from './amqp-health.indicator.js';
import { CoreHealthIndicator } from './core-health.indicator.js';
import { DatabaseHealthIndicator } from './database-health.indicator.js';
import { WorkflowHealthIndicator } from './workflow-health.indicator.js';

@Controller('health')
export class HealthController {
  public constructor(
    private readonly health: HealthCheckService,
    private readonly database: DatabaseHealthIndicator,
    private readonly amqp: AmqpHealthIndicator,
    private readonly core: CoreHealthIndicator,
    private readonly workflow: WorkflowHealthIndicator,
  ) {}

  @Get('live')
  public live(): { status: 'ok' } {
    return { status: 'ok' };
  }

  @Get('ready')
  @HealthCheck()
  public ready() {
    return this.health.check([
      () => this.database.check(),
      () => this.amqp.check(),
      () => this.core.check(),
      () => this.workflow.check(),
    ]);
  }
}
