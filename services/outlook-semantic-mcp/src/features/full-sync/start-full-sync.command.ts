import crypto from 'node:crypto';
import { createSmeared } from '@unique-ag/utils';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish } from 'remeda';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GetSubscriptionAndUserProfileQuery } from '../user-utils/get-subscription-and-user-profile.query';
import { FullSyncEventDto } from './dtos/full-sync-event.dto';

export type FullSyncRunStatus = 'skipped' | 'started';

@Injectable()
export class StartFullSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly getSubscriptionAndUserProfileQuery: GetSubscriptionAndUserProfileQuery,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(subscriptionId: string): Promise<{ status: FullSyncRunStatus }> {
    traceAttrs({ subscriptionId: subscriptionId });
    this.logger.log({ subscriptionId, msg: `Starting full sync` });

    const { userProfile } = await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    const userEmail = createSmeared(userProfile.email);
    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      userEmail,
      msg: `Resolved subscription and user profile`,
    });

    const guardResult = await this.acquireSyncLock(userProfile.id);
    if (guardResult.kind === 'skipped') {
      const attributes = {
        reason: guardResult.reason,
        lastFullSyncRunAt:
          guardResult.reason !== 'missing' ? guardResult.lastFullSyncRunAt?.toISOString() : `null`,
      };
      traceEvent('full sync skipped', attributes);
      this.logger.log({
        ...attributes,
        subscriptionId,
        userProfileId: userProfile.id,
        userEmail,
        msg: `Full sync skipped: ${guardResult.reason}`,
      });
      return { status: 'skipped' };
    }

    const event = FullSyncEventDto.parse({
      type: 'unique.outlook-semantic-mcp.full-sync.execute',
      payload: { userProfileId: userProfile.id, version: guardResult.version },
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);

    this.logger.log({
      subscriptionId,
      userProfileId: userProfile.id,
      userEmail,
      version: guardResult.version,
      msg: `Full sync execute event published`,
    });

    return { status: 'started' };
  }

  private async acquireSyncLock(userProfileId: string): Promise<AcquireLockResult> {
    return this.db.transaction(async (tx): Promise<AcquireLockResult> => {
      const inboxConfig = await tx
        .select({
          fullSyncState: inboxConfiguration.fullSyncState,
          lastFullSyncRunAt: inboxConfiguration.lastFullSyncRunAt,
          filters: inboxConfiguration.filters,
          oldestCreatedDateTime: inboxConfiguration.oldestCreatedDateTime,
          newestLastModifiedDateTime: inboxConfiguration.newestLastModifiedDateTime,
          oldestLastModifiedDateTime: inboxConfiguration.oldestLastModifiedDateTime,
        })
        .from(inboxConfiguration)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!inboxConfig) {
        return { kind: 'skipped', reason: 'missing' };
      }

      if (!['ready', 'failed'].includes(inboxConfig.fullSyncState)) {
        return {
          kind: 'skipped',
          reason: 'already running',
          lastFullSyncRunAt: inboxConfig.lastFullSyncRunAt,
        };
      }

      const fiveMinutesAgo = new Date();
      fiveMinutesAgo.setMinutes(fiveMinutesAgo.getMinutes() - 5);
      if (
        inboxConfig.fullSyncState !== 'failed' &&
        isNonNullish(inboxConfig.lastFullSyncRunAt) &&
        inboxConfig.lastFullSyncRunAt > fiveMinutesAgo
      ) {
        return {
          kind: 'skipped',
          reason: 'ran recently',
          lastFullSyncRunAt: inboxConfig.lastFullSyncRunAt,
        };
      }

      const isResume =
        isNonNullish(inboxConfig.oldestCreatedDateTime) && inboxConfig.fullSyncState === 'failed';
      const version = crypto.randomUUID();
      const now = new Date();

      const updateSet: Partial<typeof inboxConfiguration.$inferInsert> = {
        fullSyncState: 'fetching-emails',
        fullSyncVersion: version,
        lastFullSyncStartedAt: now,
      };

      if (!isResume) {
        updateSet.newestCreatedDateTime = null;
        updateSet.oldestCreatedDateTime = null;
        updateSet.newestLastModifiedDateTime = inboxConfig.newestLastModifiedDateTime ?? now;
        updateSet.oldestLastModifiedDateTime = null;
        updateSet.fullSyncNextLink = null;
      }

      await tx
        .update(inboxConfiguration)
        .set(updateSet)
        .where(eq(inboxConfiguration.userProfileId, userProfileId))
        .execute();

      return {
        kind: 'proceed',
        version,
      };
    });
  }
}

type AcquireLockResult =
  | { kind: 'skipped'; reason: 'missing' }
  | {
      kind: 'skipped';
      reason: 'already running' | 'ran recently';
      lastFullSyncRunAt: Date | null;
    }
  | {
      kind: 'proceed';
      version: string;
    };
