import { Inject, Injectable } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
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
  }: {
    userProfileId: string;
    messageId: string;
  }): Promise<void> {
    traceAttrs({ user_profile_id: userProfileId, message_id: messageId });
    await this.ingestEmailCommand.run({ userProfileId, messageId });
    await this.db
      .update(inboxConfiguration)
      .set({ messagesProcessed: sql`${inboxConfiguration.messagesProcessed} + 1` })
      .where(eq(inboxConfiguration.userProfileId, userProfileId));
  }
}
