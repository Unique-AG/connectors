import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { DrizzleModule } from '~/db/drizzle.module';
import { PersistentCacheModule } from '~/features/persistent-cache/persistent-cache.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { AmqpHealthIndicator } from './amqp-health.indicator';
import { DatabaseHealthIndicator } from './database-health.indicator';
import { HealthController } from './health.controller';
import { McpProcessesHealthIndicator } from './mcp-processes-health.indicator';
import { MsGraphConnectivityHealthIndicator } from './ms-graph-connectivity-health.indicator';

@Module({
  imports: [TerminusModule, UniqueApiFeatureModule, DrizzleModule, PersistentCacheModule],
  controllers: [HealthController],
  providers: [
    MsGraphConnectivityHealthIndicator,
    DatabaseHealthIndicator,
    AmqpHealthIndicator,
    McpProcessesHealthIndicator,
  ],
})
export class HealthModule {}
