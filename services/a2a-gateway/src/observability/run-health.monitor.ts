import { Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { UsageRepository } from '../drizzle/usage.repository.js';
import { MaintenanceService } from '../workflow/maintenance.service.js';
import { GatewayMetrics } from './gateway-metrics.service.js';

const STUCK_AFTER_MS = 15 * 60_000;

/**
 * Publishes active/stuck run gauges every maintenance tick and logs stuck runs as a warning an
 * alert can match on. Counts only; no ids of users or content.
 */
@Injectable()
export class RunHealthMonitor implements OnModuleInit {
  private readonly logger = new Logger(RunHealthMonitor.name);

  public constructor(
    private readonly maintenance: MaintenanceService,
    private readonly metrics: GatewayMetrics,
    private readonly usage: UsageRepository,
  ) {}

  public onModuleInit(): void {
    this.maintenance.register('observability.run-health', () => this.check());
  }

  public async check(): Promise<void> {
    const health = await this.usage.runHealth(new Date(Date.now() - STUCK_AFTER_MS));
    this.metrics.observeRuns(health);
    for (const entry of health.filter((row) => row.stuck > 0)) {
      this.logger.warn({
        alert: 'a2a-stuck-runs',
        companyId: entry.companyId,
        direction: entry.direction,
        stuck: entry.stuck,
      });
    }
  }
}
