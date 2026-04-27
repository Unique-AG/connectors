import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { HealthConfigNamespaced } from '../config';
import type { SyncRecord } from './sync-result.types';

export type { SyncRecord, SyncResult, SyncStep } from './sync-result.types';
export { SyncStep as SyncStepValues } from './sync-result.types';

@Injectable()
export class SyncStatusStore {
  private readonly maxSize: number;
  private readonly recordsByTenant = new Map<string, SyncRecord[]>();

  public constructor(configService: ConfigService<HealthConfigNamespaced, true>) {
    this.maxSize = configService.get('health.syncHistorySize', { infer: true });
  }

  public record(syncRecord: SyncRecord): void {
    const existing = this.recordsByTenant.get(syncRecord.tenantName) ?? [];
    if (existing.length >= this.maxSize) {
      existing.shift();
    }
    existing.push(syncRecord);
    this.recordsByTenant.set(syncRecord.tenantName, existing);
  }

  public getRecordsByTenant(): ReadonlyMap<string, readonly SyncRecord[]> {
    const snapshot = new Map<string, readonly SyncRecord[]>();
    for (const [tenant, records] of this.recordsByTenant) {
      snapshot.set(tenant, [...records]);
    }
    return snapshot;
  }

  public getLatest(): SyncRecord | undefined {
    let latest: SyncRecord | undefined;
    for (const records of this.recordsByTenant.values()) {
      const candidate = records[records.length - 1];
      if (!candidate) {
        continue;
      }
      if (!latest || candidate.timestamp.getTime() > latest.timestamp.getTime()) {
        latest = candidate;
      }
    }
    return latest;
  }
}
