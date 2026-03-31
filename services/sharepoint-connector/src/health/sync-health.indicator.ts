import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { isNullish } from 'remeda';
import { Config } from '../config';
import { SyncStatusStore } from './sync-status.store';

interface SiteStats {
  failures: number;
  total: number;
}

@Injectable()
export class SyncHealthIndicator {
  private readonly threshold: number;

  public constructor(
    private readonly store: SyncStatusStore,
    private readonly healthIndicatorService: HealthIndicatorService,
    configService: ConfigService<Config, true>,
  ) {
    this.threshold = configService.get('health.syncSiteFailureThreshold', { infer: true });
  }

  public check(key: string): HealthIndicatorResult {
    const records = this.store.getRecords();
    const latest = this.store.getLatest();

    if (isNullish(latest)) {
      return {};
    }

    const indicator = this.healthIndicatorService.check(key);
    const sites = new Map<string, SiteStats>();

    // First pass: accumulate per-site stats from records that have site-level detail.
    for (const record of records) {
      for (const { siteId, result } of record.siteResults) {
        const stats = sites.get(siteId) ?? { failures: 0, total: 0 };
        stats.total++;
        if (result.status === 'failure') {
          stats.failures++;
        }
        sites.set(siteId, stats);
      }
    }

    // Second pass: when a full sync failed before reaching per-site processing (e.g. config
    // loading error), count it as a failure for every site already known from other records.
    for (const record of records) {
      if (record.fullResult.status === 'failure' && record.siteResults.length === 0) {
        for (const stats of sites.values()) {
          stats.total++;
          stats.failures++;
        }
      }
    }

    const allFullSyncFailures = records.every((r) => r.fullResult.status === 'failure');

    // If every record is a full-sync failure and no per-site data exists, we still know
    // the connector is unhealthy even though we can't attribute it to specific sites.
    if (allFullSyncFailures && sites.size === 0) {
      return indicator.down({
        lastSyncAt: latest.timestamp.toISOString(),
        threshold: this.threshold,
        failingSites: [],
        sites: {},
      });
    }

    const sitesRecord: Record<string, SiteStats> = Object.fromEntries(sites);
    const failingSites = [...sites.entries()]
      .filter(([, stats]) => stats.failures / stats.total > this.threshold)
      .map(([siteId]) => siteId);

    if (failingSites.length > 0) {
      return indicator.down({
        lastSyncAt: latest.timestamp.toISOString(),
        threshold: this.threshold,
        failingSites,
        sites: sitesRecord,
      });
    }

    return indicator.up({
      lastSyncAt: latest.timestamp.toISOString(),
      recentSyncs: records.length,
      sites: sitesRecord,
    });
  }
}
