import crypto from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';

@Injectable()
export class FullSyncResetCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Span()
  public async run(userProfileId: string): Promise<{ version: string }> {
    const version = crypto.randomUUID();

    await this.db
      .update(inboxConfiguration)
      .set({
        fullSyncVersion: version,
        fullSyncNextLink: null,
        fullSyncBatchIndex: 0,
        fullSyncSkipped: 0,
        fullSyncScheduledForIngestion: 0,
        fullSyncFailedToUploadForIngestion: 0,
        fullSyncExpectedTotal: null,
        fullSyncLastRunAt: null,
        fullSyncState: 'ready',
      })
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .execute();

    this.logger.log({ userProfileId, version, msg: 'Full sync reset' });

    return { version };
  }
}
