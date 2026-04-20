import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import {
  DRIZZLE,
  DrizzleDatabase,
  directories,
  directoriesSync,
  inboxConfigurations,
  UserProfile,
  userProfiles,
} from '~/db';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { isWithinCooldown } from '~/utils/is-within-cooldown';
import { SubscriptionRemoveService } from '../subscriptions/subscription-remove.service';

export const STALE_DELETE_INBOX_CONFIGURATION_THRESHOLD_IN_MINUTES = 20;

@Injectable()
export class ExecuteInboxDeletionCommand {
  private readonly logger = new Logger(ExecuteInboxDeletionCommand.name);

  public constructor(
    private readonly subscriptionRemove: SubscriptionRemoveService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  public async run(userProfileId: string): Promise<void> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    if (!userProfile) {
      this.logger.log({ userProfileId, msg: 'No user profile found, skipping deletion' });
      return;
    }

    const logContext: Readonly<Record<string, string>> = Object.freeze({
      userProfileId,
      providerUserId: userProfile.providerUserId,
      userEmail: createSmeared(userProfile.email ?? '').toString(),
    });

    const inboxConfiguration = await this.db.query.inboxConfigurations.findFirst({
      where: eq(inboxConfigurations.userProfileId, userProfile.id),
    });

    if (!inboxConfiguration) {
      this.logger.log({ ...logContext, msg: 'No inbox configuration found, skipping deletion' });
      return;
    }
    if (!inboxConfiguration.deletingInboxStartedAt) {
      this.logger.log({
        ...logContext,
        msg: 'Inbox configuration deletingInboxStartedAt is null, skipping deletion',
      });
      return;
    }
    if (
      isWithinCooldown(
        inboxConfiguration.deletingHeartbeatAt,
        STALE_DELETE_INBOX_CONFIGURATION_THRESHOLD_IN_MINUTES,
      )
    ) {
      this.logger.log({
        ...logContext,
        msg: 'Inbox configuration deletingHeartbeatAt is within couldown, skipping deletion',
      });
      return;
    }

    await this.subscriptionRemove.removeByUserProfileId(
      convertUserProfileIdToTypeId(userProfile.id),
    );
    this.logger.warn({ ...logContext, msg: `Subscription Deleted` });
    await this.updateDeletingHeartbeatAt(userProfile.id);

    await this.deleteContentAndScope(userProfile, logContext);
    this.logger.warn({ ...logContext, msg: `Content and scope Deleted` });

    await this.db.delete(directoriesSync).where(eq(directoriesSync.userProfileId, userProfile.id));
    await this.updateDeletingHeartbeatAt(userProfile.id);
    this.logger.warn({ userProfileId, msg: 'Directories Sync deleted' });

    await this.db.delete(directories).where(eq(directories.userProfileId, userProfileId));
    await this.updateDeletingHeartbeatAt(userProfile.id);
    this.logger.warn({ userProfileId, msg: 'Directories deleted' });

    await this.db
      .delete(inboxConfigurations)
      .where(eq(inboxConfigurations.userProfileId, userProfileId));
    this.logger.warn({ userProfileId, msg: 'InboxConfiguration deleted' });

    this.logger.warn({ userProfileId, msg: 'Inbox deletion finished' });
  }

  private async deleteContentAndScope(
    userProfile: UserProfile,
    logContext: Readonly<Record<string, string>>,
  ): Promise<void> {
    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );

    if (!rootScope) {
      return;
    }

    let deletedTotal = 0;
    while (true) {
      const ids = await this.uniqueApi.files.getIdsByScope(rootScope.id, 100);
      if (ids.length === 0) {
        break;
      }
      await this.uniqueApi.files.deleteByIds(ids);
      deletedTotal += ids.length;
      await this.updateDeletingHeartbeatAt(userProfile.id);
      this.logger.warn({
        ...logContext,
        deletedTotal,
        msg: 'Deleted file batch, heartbeat updated',
      });
    }
    this.logger.warn({
      ...logContext,
      deletedTotal,
      msg: 'File deletion complete',
    });
    await this.uniqueApi.scopes.delete(rootScope.id, { recursive: true });
    this.logger.warn({
      ...logContext,
      deletedTotal,
      msg: 'Scope deletion complete',
    });
  }

  private async updateDeletingHeartbeatAt(userProfileId: string): Promise<void> {
    await this.db
      .update(inboxConfigurations)
      .set({ deletingHeartbeatAt: sql`NOW()` })
      .where(
        and(
          isNotNull(inboxConfigurations.deletingInboxStartedAt),
          eq(inboxConfigurations.userProfileId, userProfileId),
        ),
      )
      .returning();
  }
}
