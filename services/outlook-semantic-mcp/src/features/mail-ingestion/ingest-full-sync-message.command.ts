import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { IngestEmailCommand } from './ingest-email.command';

@Injectable()
export class IngestFullSyncMessageCommand {
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
    const inboxConfig = await this.db.query.inboxConfiguration.findFirst({
      columns: { fullSyncVersion: true },
      where: eq(inboxConfiguration.userProfileId, userProfileId),
    });
    assert.ok(inboxConfig, `Missing inbox configuration for user profile`);

    if (inboxConfig.fullSyncVersion !== fullSyncVersion) {
      return;
    }

    await this.ingestEmailCommand.run({
      userProfileId,
      messageId,
    });
  }
}
