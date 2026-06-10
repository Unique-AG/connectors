import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, notInArray, sql } from 'drizzle-orm';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  delegatedAccessDirectories,
  directories,
  userProfiles,
} from '~/db';
import { DelegatedAccessInfoDto } from './delegated-access-info.dto';

@Injectable()
export class GetDirectoryDelegatedAccessQuery {
  public constructor(
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(userProfileId: string): Promise<DelegatedAccessInfoDto[]> {
    if (this.config.scan === 'disabled') {
      return [];
    }

    const directoriesIgnoredForSync = this.db
      .selectDistinct({ microsoftDirectoryId: directories.providerDirectoryId })
      .from(directories)
      .where(eq(directories.ignoreForSync, true));

    return await this.db
      .select({
        ownerUserEmail: sql<string>`${userProfiles.email}`,
        ownerUserId: delegatedAccessAccounts.ownerUserId,
        ownerProviderUserId: sql<string>`${userProfiles.providerUserId}`,
        msGraphDirectoryIds: sql<string[]>`array_agg(${delegatedAccessDirectories.directoryId})`,
        hasFullDelegatedAccess: sql<boolean>`false`,
      })
      .from(delegatedAccessAccounts)
      .innerJoin(
        delegatedAccessDirectories,
        eq(delegatedAccessAccounts.id, delegatedAccessDirectories.accountsId),
      )
      .innerJoin(userProfiles, eq(delegatedAccessAccounts.ownerUserId, userProfiles.id))
      .where(
        and(
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, false),
          eq(delegatedAccessAccounts.delegateUserId, userProfileId),
          isNotNull(userProfiles.providerUserId),
          isNotNull(userProfiles.email),
          notInArray(delegatedAccessDirectories.directoryId, directoriesIgnoredForSync),
        ),
      )
      .groupBy(
        userProfiles.providerUserId,
        userProfiles.email,
        delegatedAccessAccounts.ownerUserId,
      );
  }
}
