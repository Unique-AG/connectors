import { Global, Module } from '@nestjs/common';
import { OpenTelemetryModule } from 'nestjs-otel';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { DrizzleModule } from '../drizzle/drizzle.module.js';
import { UsageRepository } from '../drizzle/usage.repository.js';
import { UniqueModule } from '../unique/unique.module.js';
import { WorkflowModule } from '../workflow/workflow.module.js';
import { AuditLog } from './audit-log.service.js';
import { GatewayMetrics } from './gateway-metrics.service.js';
import { QuotaService } from './quota.service.js';
import { RunHealthMonitor } from './run-health.monitor.js';
import { UsageController } from './usage.controller.js';

@Global()
@Module({
  imports: [
    DrizzleModule,
    UniqueModule,
    WorkflowModule,
    OpenTelemetryModule.forRoot({ metrics: { hostMetrics: true } }),
  ],
  controllers: [UsageController],
  providers: [
    AuditLog,
    GatewayMetrics,
    KongIdentityGuard,
    QuotaService,
    RunHealthMonitor,
    UsageRepository,
  ],
  exports: [AuditLog, GatewayMetrics, QuotaService, UsageRepository],
})
export class ObservabilityModule {}
