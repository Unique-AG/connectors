import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/drizzle';
import { traceAttrs } from '~/email-sync/tracing.utils';
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
    traceAttrs({ subscription_id: subscriptionId, message_id: messageId });
    const subscription = await this.db.query.subscriptions.findFirst({
      columns: { userProfileId: true },
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });

    assert.ok(subscription, `Subscription missing for: ${subscriptionId}`);
    await this.ingestEmailCommand.run({
      userProfileId: subscription.userProfileId,
      messageId,
    });
  }
}
