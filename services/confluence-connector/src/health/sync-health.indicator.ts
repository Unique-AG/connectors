import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { isNullish } from 'remeda';
import type { HealthConfigNamespaced } from '../config';
import { SyncStatusStore } from './sync-status.store';

interface TenantStats {
  failures: number;
  total: number;
}

@Injectable()
export class SyncHealthIndicator {
  private readonly threshold: number;

  public constructor(
    private readonly store: SyncStatusStore,
    private readonly healthIndicatorService: HealthIndicatorService,
    configService: ConfigService<HealthConfigNamespaced, true>,
  ) {
    this.threshold = configService.get('health.syncTenantFailureThreshold', { infer: true });
  }

  public check(key: string): HealthIndicatorResult {
    const indicator = this.healthIndicatorService.check(key);
    const recordsByTenant = this.store.getRecordsByTenant();
    const latest = this.store.getLatest();

    if (isNullish(latest)) {
      return indicator.up({ message: 'No sync records yet' });
    }

    const tenants: Record<string, TenantStats> = {};
    const failingTenants: string[] = [];

    for (const [tenantName, records] of recordsByTenant) {
      const stats: TenantStats = { failures: 0, total: 0 };
      for (const record of records) {
        stats.total++;
        if (record.result.status === 'failure') {
          stats.failures++;
        }
      }
      tenants[tenantName] = stats;

      if (stats.total > 0 && stats.failures / stats.total > this.threshold) {
        failingTenants.push(tenantName);
      }
    }

    if (failingTenants.length > 0) {
      return indicator.down({
        lastSyncAt: latest.timestamp.toISOString(),
        threshold: this.threshold,
        failingTenants,
        tenants,
      });
    }

    return indicator.up({
      lastSyncAt: latest.timestamp.toISOString(),
      tenants,
    });
  }
}
