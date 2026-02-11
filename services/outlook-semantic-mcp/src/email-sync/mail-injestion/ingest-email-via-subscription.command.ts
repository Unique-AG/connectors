import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/drizzle';
import { IngestEmailCommand } from './ingest-email.command';

@Injectable()
export class IngestEmailViaSubscriptionCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly ingestEmailCommand: IngestEmailCommand,
  ) {}

  public async run({
    subscriptionId,
    messageId,
  }: {
    subscriptionId: string;
    messageId: string;
  }): Promise<void> {
    const subscription = await this.db.query.subscriptions.findFirst({
      columns: { userProfileId: true },
      where: eq(subscriptions.id, subscriptionId),
    });

    assert.ok(subscription, `Subscription missing for: ${subscriptionId}`);
    await this.ingestEmailCommand.run({
      userProfileId: subscription.userProfileId,
      messageId,
    });
  }
}
