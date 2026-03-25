import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs } from '~/features/tracing.utils';
import { IngestEmailCommand } from './ingest-email.command';

@Injectable()
export class IngestEmailLiveCatchupMessageCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly ingestEmailCommand: IngestEmailCommand,
  ) {}

  @Span()
  public async run({
    subscriptionId,
    messageId,
  }: {
    subscriptionId: string;
    messageId: string;
  }): Promise<void> {
    traceAttrs({ subscriptionId: subscriptionId, messageId: messageId });
    const subscription = await this.db.query.subscriptions.findFirst({
      columns: { userProfileId: true },
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });

    assert.ok(subscription, `Subscription missing for: ${subscriptionId}`);

    const inboxConfig = await this.db.query.inboxConfigurations.findFirst({
      columns: { filters: true },
      where: eq(inboxConfigurations.userProfileId, subscription.userProfileId),
    });

    // For live catchup there is no point in checking the version because.
    // 1. Live catchup should be fairly fast and the version would change quite ofter
    // 2. We can have the case that live catchup finished -> we started a new one and we still have to process the last batch
    //    so this will lead in dropping messages which we need to process.
    const filters = inboxConfig
      ? inboxConfigurationMailFilters.parse(inboxConfig.filters)
      : undefined;

    await this.ingestEmailCommand.run({
      userProfileId: subscription.userProfileId,
      messageId,
      // Filters are applied client-side here because live catchup queries by updatedAt rather than
      // receivedAt, so the Graph API cannot enforce sender/folder filters on our behalf.
      filters,
    });
  }
}
