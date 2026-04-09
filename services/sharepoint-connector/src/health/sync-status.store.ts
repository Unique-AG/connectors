import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import type { SyncRecord } from '../sharepoint-synchronization/sync-result.types';

export type {
  FullSyncResult,
  SiteResultEntry,
  SiteSyncResult,
  SyncRecord,
  SyncResult,
} from '../sharepoint-synchronization/sync-result.types';

@Injectable()
export class SyncStatusStore {
  private readonly maxSize: number;
  private readonly records: SyncRecord[] = [];

  public constructor(configService: ConfigService<Config, true>) {
    this.maxSize = configService.get('health.syncHistorySize', { infer: true });
  }

  public record(syncRecord: SyncRecord): void {
    if (this.records.length >= this.maxSize) {
      this.records.shift();
    }
    this.records.push(syncRecord);
  }

  public getRecords(): readonly SyncRecord[] {
    return [...this.records];
  }

  public getLatest(): SyncRecord | undefined {
    return this.records[this.records.length - 1];
  }
}
