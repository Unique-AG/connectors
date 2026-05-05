import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, sql } from 'drizzle-orm';
import { AppConfig, appConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessPipelines,
  directories,
  userProfiles,
} from '~/db';
import { DelegatedAccessInfoDto } from './delegated-access-info.dto';

@Injectable()
export class GetFullDelegatedAccessQuery {
  public constructor(
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(userProfileId: string): Promise<DelegatedAccessInfoDto[]> {
    if (this.config.delegatedAccessScan === 'disabled') {
      return [];
    }

    return await this.db
      .select({
        ownerUserEmail: sql<string>`${userProfiles.email}`,
        ownerUserId: delegatedAccessPipelines.ownerUserId,
        ownerProviderUserId: sql<string>`${userProfiles.providerUserId}`,
        msGraphDirectoryIds: sql<string[]>`array_agg(${directories.providerDirectoryId})`,
      })
      .from(delegatedAccessPipelines)
      .innerJoin(userProfiles, eq(delegatedAccessPipelines.ownerUserId, userProfiles.id))
      .innerJoin(
        directories,
        and(
          eq(directories.ignoreForSync, false),
          eq(delegatedAccessPipelines.ownerUserId, directories.userProfileId),
        ),
      )
      .where(
        and(
          eq(delegatedAccessPipelines.hasFullDelegatedAccess, true),
          eq(delegatedAccessPipelines.delegateUserId, userProfileId),
          isNotNull(userProfiles.providerUserId),
          isNotNull(userProfiles.email),
        ),
      )
      .groupBy(
        userProfiles.providerUserId,
        userProfiles.email,
        delegatedAccessPipelines.ownerUserId,
      );
  }
}
