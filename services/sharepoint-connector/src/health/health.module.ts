import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { TerminusModule } from '@nestjs/terminus';
import { healthConfig } from './health.config';
import { HealthController } from './health.controller';
import { VersionHealthIndicator } from './version-health.service';

@Module({
  imports: [TerminusModule, ConfigModule.forFeature(healthConfig)],
  controllers: [HealthController],
  providers: [VersionHealthIndicator],
})
export class HealthModule {}
