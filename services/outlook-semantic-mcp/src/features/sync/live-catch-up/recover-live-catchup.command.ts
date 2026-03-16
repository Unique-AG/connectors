import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { LiveCatchUpCommand } from './live-catch-up.command';

@Injectable()
export class RecoverLiveCatchupCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly liveCatchUpCommand: LiveCatchUpCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run({ userProfileId }: { userProfileId: string }): Promise<void> {
    this.logger.log({ msg: 'Live catch-up recovery requested', userProfileId });

    await this.db
      .update(inboxConfiguration)
      .set({ liveCatchUpState: 'ready' })
      .where(eq(inboxConfiguration.userProfileId, userProfileId))
      .execute();

    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });

    if (!subscription) {
      this.logger.warn({
        msg: 'No subscription found for user profile during recovery, skipping live catchup recovery',
        userProfileId,
      });
      return;
    }

    this.logger.log({
      msg: 'Triggering live catchup for recovered inbox',
      userProfileId,
      subscriptionId: subscription.subscriptionId,
    });

    await this.liveCatchUpCommand.run({ subscriptionId: subscription.subscriptionId });
  }
}
