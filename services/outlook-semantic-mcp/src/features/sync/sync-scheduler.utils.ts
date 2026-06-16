import { and, eq, gt, isNotNull, sql } from 'drizzle-orm';
import { alias, union } from 'drizzle-orm/pg-core';
import { DrizzleDatabase, delegatedAccessAccounts, subscriptions, userProfiles } from '~/db';

const delegateProfiles = alias(userProfiles, 'delegate_profiles');

export function selectUserProfileIdsWhichCanRunTheSyncProcess(db: DrizzleDatabase) {
  const withActiveSubscription = db
    .select({ userProfileId: subscriptions.userProfileId })
    .from(subscriptions)
    .where(gt(subscriptions.expiresAt, sql`NOW()`));

  const sharedMailboxWithLiveDelegate = db
    .select({ userProfileId: delegatedAccessAccounts.ownerUserId })
    .from(delegatedAccessAccounts)
    .innerJoin(
      delegateProfiles,
      and(
        eq(delegateProfiles.id, delegatedAccessAccounts.delegateUserId),
        isNotNull(delegateProfiles.accessToken),
      ),
    )
    .innerJoin(
      userProfiles,
      and(
        eq(userProfiles.id, delegatedAccessAccounts.ownerUserId),
        eq(userProfiles.source, 'shared-mailbox'),
      ),
    );

  return union(withActiveSubscription, sharedMailboxWithLiveDelegate);
}
