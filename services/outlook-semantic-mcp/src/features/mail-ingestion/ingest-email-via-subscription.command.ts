import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs } from '~/features/tracing.utils';
import { IngestEmailCommand } from './ingest-email.command';

@Injectable()
export class IngestEmailViaSubscriptionCommand {
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

    const inboxConfig = await this.db.query.inboxConfiguration.findFirst({
      columns: { filters: true },
      where: eq(inboxConfiguration.userProfileId, subscription.userProfileId),
    });

    const filters = inboxConfig ? inboxConfigurationMailFilters.parse(inboxConfig.filters) : undefined;

    await this.ingestEmailCommand.run({
      userProfileId: subscription.userProfileId,
      messageId,
      filters,
    });
  }
}
