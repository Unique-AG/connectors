import { HttpException, HttpStatus, Inject, Injectable } from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { UsageRepository } from '../drizzle/usage.repository.js';
import { AuditLog } from './audit-log.service.js';
import { type Direction, GatewayMetrics } from './gateway-metrics.service.js';

export class QuotaExceededError extends HttpException {
  public constructor(public readonly scope: string) {
    super(`concurrency quota exceeded (${scope})`, HttpStatus.TOO_MANY_REQUESTS);
  }
}

/** Concurrency limits that contain cost and abuse per tenant and per remote connection. */
@Injectable()
export class QuotaService {
  public constructor(
    private readonly usage: UsageRepository,
    private readonly metrics: GatewayMetrics,
    private readonly audit: AuditLog,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async assertOutbound(companyId: string, connectionId: string): Promise<void> {
    if (
      (await this.usage.activeExecutions(companyId)) >= this.config.maxActiveExecutionsPerTenant
    ) {
      this.reject(companyId, 'outbound', 'tenant');
    }
    if (
      (await this.usage.activeExecutions(companyId, connectionId)) >=
      this.config.maxActiveExecutionsPerConnection
    ) {
      this.reject(companyId, 'outbound', 'connection');
    }
  }

  public async assertInbound(companyId: string): Promise<void> {
    if ((await this.usage.activeTasks(companyId)) >= this.config.maxActiveTasksPerTenant) {
      this.reject(companyId, 'inbound', 'tenant');
    }
  }

  private reject(companyId: string, direction: Direction, scope: string): never {
    this.metrics.quotaRejected(companyId, direction, scope);
    this.audit.record('quota.rejected', { companyId }, { direction, scope });
    throw new QuotaExceededError(scope);
  }
}
