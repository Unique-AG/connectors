import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { SyncStep } from '../constants/sync-step.enum';

export type SiteSyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: SyncStep }
  | { status: 'skipped'; reason: string };

export type FullSyncResult =
  | { status: 'success' }
  | { status: 'failure'; step: SyncStep }
  | { status: 'skipped'; reason: string };

export interface SiteResultEntry {
  siteId: string;
  result: SiteSyncResult;
}

export interface SyncRecord {
  timestamp: Date;
  fullResult: FullSyncResult;
  siteResults: SiteResultEntry[];
}

@Injectable()
export class SyncStatusStore {
  private readonly maxSize: number;
  private readonly records: SyncRecord[] = [];

  constructor(configService: ConfigService<Config, true>) {
    this.maxSize = configService.get('health.syncHistorySize', { infer: true });
  }

  record(syncRecord: SyncRecord): void {
    if (this.records.length >= this.maxSize) {
      this.records.shift();
    }
    this.records.push(syncRecord);
  }

  getRecords(): readonly SyncRecord[] {
    return [...this.records];
  }

  getLatest(): SyncRecord | undefined {
    return this.records[this.records.length - 1];
  }
}
