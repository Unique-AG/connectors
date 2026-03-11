import { Inject, Injectable } from '@nestjs/common';
import { and, eq, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { traceAttrs } from '~/features/tracing.utils';
import { IngestEmailCommand } from './ingest-email.command';

@Injectable()
export class IngestEmailFromFullSyncCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly ingestEmailCommand: IngestEmailCommand,
  ) {}

  @Span()
  public async run({
    userProfileId,
    messageId,
    fullSyncVersion,
  }: {
    userProfileId: string;
    messageId: string;
    fullSyncVersion: string;
  }): Promise<void> {
    traceAttrs({ userProfileId: userProfileId, messageId: messageId });
    await this.ingestEmailCommand.run({ userProfileId, messageId });
    await this.db
      .update(inboxConfiguration)
      .set({ messagesProcessed: sql`${inboxConfiguration.messagesProcessed} + 1` })
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfileId),
          eq(inboxConfiguration.fullSyncVersion, fullSyncVersion),
        ),
      );
  }
}
