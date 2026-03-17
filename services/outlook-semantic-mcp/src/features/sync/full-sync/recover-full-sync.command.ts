import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { StartFullSyncCommand } from './start-full-sync.command';

@Injectable()
export class RecoverFullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly startFullSyncCommand: StartFullSyncCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run({ userProfileId }: { userProfileId: string }): Promise<void> {
    this.logger.log({ msg: 'Full sync recovery requested', userProfileId });

    await this.db
      .update(inboxConfiguration)
      .set({ fullSyncState: 'ready' })
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .execute();

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });

    if (!subscription) {
      this.logger.warn({
        msg: 'No subscription found for user profile during recovery, skipping full sync',
        userProfileId,
      });
      return;
    }

    this.logger.log({
      msg: 'Triggering full sync for recovered inbox',
      userProfileId,
      subscriptionId: subscription.subscriptionId,
    });

    await this.startFullSyncCommand.run(subscription.subscriptionId);
  }
}
