import { Client } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import type { SyncJob as SyncJobRow } from '../drizzle';

type SyncResult = {
  durationMs: number;
  newSubscription: boolean;
};

export class SyncJob {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    public readonly syncJob: SyncJobRow,
    public readonly graphClient: Client,
  ) {}

  public async run(): Promise<SyncResult> {
    const start = performance.now();

    this.logger.log({
      msg: 'Running sync job for user profile',
      userProfileId: this.syncJob.userProfileId,
    });

    return { durationMs: performance.now() - start, newSubscription: false };
  }
}
