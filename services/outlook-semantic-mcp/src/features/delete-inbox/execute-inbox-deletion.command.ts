import { UniqueApiClient } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import { isNullish } from 'remeda';
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
      source: userProfile.source,
    });

    const decision = await this.acquireLockAndDecide(userProfileId);
    if (decision.action === 'skip') {
      this.logger.log({ ...logContext, msg: decision.message });
      return;
    }
    this.logger.log({ ...logContext, msg: `Deleting inbox configuration` });
    await this.subscriptionRemove.removeByUserProfileId(
      convertUserProfileIdToTypeId(userProfile.id),
    );
    this.logger.warn({ ...logContext, msg: `Subscription Deleted` });
    await this.updateDeletingHeartbeatAt(userProfile.id);

    await this.deleteContentAndScope(userProfile, logContext);
    this.logger.warn({ ...logContext, msg: `Content and scope Deleted` });

    await this.db.delete(directoriesSync).where(eq(directoriesSync.userProfileId, userProfile.id));
    await this.updateDeletingHeartbeatAt(userProfile.id);
    this.logger.warn({ ...logContext, msg: 'Directories Sync deleted' });

    await this.db.delete(directories).where(eq(directories.userProfileId, userProfileId));
    await this.updateDeletingHeartbeatAt(userProfile.id);
    this.logger.warn({ ...logContext, msg: 'Directories deleted' });

    if (userProfile.source === 'shared-mailbox') {
      // We delete the user profile only for shared-mailboxes because the delete command is accessible
      // via a tool call, the user will call the tool, and after that he could call reconnect inbox, if
      // we delete the user profile he will not be authenticated anymore and the Mcp will be in a weird
      // state.
      await this.db.delete(userProfiles).where(eq(userProfiles.id, userProfile.id));
      this.logger.warn({
        ...logContext,
        msg: 'Deleted user profile and InboxConfiguration for shared-mailbox',
      });
    } else {
      await this.db
        .delete(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfileId));
      this.logger.warn({
        ...logContext,
        msg: 'InboxConfiguration deleted',
      });
    }

    this.logger.warn({ ...logContext, msg: 'Inbox deletion finished' });
  }

  private async acquireLockAndDecide(
    userProfileId: string,
  ): Promise<{ action: 'skip'; message: string } | { action: 'proceed' }> {
    return await this.db.transaction(async (tx) => {
      const row = await tx
        .select({
          deletingHeartbeatAt: inboxConfigurations.deletingHeartbeatAt,
          deletingInboxStartedAt: inboxConfigurations.deletingInboxStartedAt,
        })
        .from(inboxConfigurations)
        .where(eq(inboxConfigurations.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!row) {
        return { action: 'skip', message: 'No inbox configuration found, skipping deletion' };
      }
      if (!row.deletingInboxStartedAt) {
        return {
          action: 'skip',
          message: 'Inbox configuration deletingInboxStartedAt is null, skipping deletion',
        };
      }
      const updateHeartbeat = async (): Promise<void> => {
        await tx
          .update(inboxConfigurations)
          .set({ deletingHeartbeatAt: sql`NOW()` })
          .where(eq(inboxConfigurations.userProfileId, userProfileId));
      };

      if (isNullish(row.deletingHeartbeatAt)) {
        await updateHeartbeat();
        return { action: 'proceed' };
      }
      if (
        isWithinCooldown(
          row.deletingHeartbeatAt,
          STALE_DELETE_INBOX_CONFIGURATION_THRESHOLD_IN_MINUTES,
        )
      ) {
        return {
          action: 'skip',
          message: 'Inbox configuration deletingHeartbeatAt is within cooldown, skipping deletion',
        };
      }
      await updateHeartbeat();
      return { action: 'proceed' };
    });
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
      const ids = await this.uniqueApi.files.getIdsByScope(rootScope.id, 0, 100);
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
