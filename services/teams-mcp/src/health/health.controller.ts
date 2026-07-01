import { Controller, Get } from '@nestjs/common';
import { HealthCheck, HealthCheckService } from '@nestjs/terminus';
import { AmqpHealthIndicator } from './amqp-health.indicator';
import { DatabaseHealthIndicator } from './database-health.indicator';
import { MsGraphConnectivityHealthIndicator } from './ms-graph-connectivity-health.indicator';
import { SubscriptionHealthIndicator } from './subscription-health.indicator';

@Controller('health')
export class HealthController {
  public constructor(
    private readonly healthCheckService: HealthCheckService,
    private readonly databaseIndicator: DatabaseHealthIndicator,
    private readonly amqpIndicator: AmqpHealthIndicator,
    private readonly connectivityIndicator: MsGraphConnectivityHealthIndicator,
    private readonly subscriptionIndicator: SubscriptionHealthIndicator,
  ) {}

  @Get()
  @HealthCheck()
  public check() {
    return this.healthCheckService.check([
      () => this.databaseIndicator.check('database'),
      () => this.amqpIndicator.check('amqp'),
      () => this.connectivityIndicator.check('connectivity'),
      () => this.subscriptionIndicator.check('subscription'),
    ]);
  }
}
