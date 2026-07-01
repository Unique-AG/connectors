import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { AmqpHealthIndicator } from './amqp-health.indicator';
import { DatabaseHealthIndicator } from './database-health.indicator';
import { HealthController } from './health.controller';
import { MsGraphConnectivityHealthIndicator } from './ms-graph-connectivity-health.indicator';
import { SubscriptionHealthIndicator } from './subscription-health.indicator';

@Module({
  imports: [TerminusModule, DrizzleModule],
  controllers: [HealthController],
  providers: [
    DatabaseHealthIndicator,
    AmqpHealthIndicator,
    MsGraphConnectivityHealthIndicator,
    SubscriptionHealthIndicator,
  ],
})
export class HealthModule {}
