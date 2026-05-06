import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, directories, userProfiles } from '~/db';
import { DelegatedAccessInfoDto } from './delegated-access-info.dto';

@Injectable()
export class GetFullDelegatedAccessQuery {
  public constructor(
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(userProfileId: string): Promise<DelegatedAccessInfoDto[]> {
    if (this.config.scan === 'disabled') {
      return [];
    }

    // This query is the same as GetMailboxesWithFullDelegatedAccessQuery but it also returns the directories
    // to which a user has delegated accessf
    return await this.db
      .select({
        ownerUserEmail: sql<string>`${userProfiles.email}`,
        ownerUserId: delegatedAccessAccounts.ownerUserId,
        ownerProviderUserId: sql<string>`${userProfiles.providerUserId}`,
        msGraphDirectoryIds: sql<string[]>`array_agg(${directories.providerDirectoryId})`,
      })
      .from(delegatedAccessAccounts)
      .innerJoin(userProfiles, eq(delegatedAccessAccounts.ownerUserId, userProfiles.id))
      .innerJoin(
        directories,
        and(
          eq(directories.ignoreForSync, false),
          eq(delegatedAccessAccounts.ownerUserId, directories.userProfileId),
        ),
      )
      .where(
        and(
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, true),
          eq(delegatedAccessAccounts.delegateUserId, userProfileId),
          isNotNull(userProfiles.providerUserId),
          isNotNull(userProfiles.email),
        ),
      )
      .groupBy(
        userProfiles.providerUserId,
        userProfiles.email,
        delegatedAccessAccounts.ownerUserId,
      );
  }
}
