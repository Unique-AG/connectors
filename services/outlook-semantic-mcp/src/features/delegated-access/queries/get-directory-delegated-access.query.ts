import { Inject, Injectable } from '@nestjs/common';
import { and, eq, isNotNull, notInArray, sql } from 'drizzle-orm';
import { AppConfig, appConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessDirectories,
  delegatedAccessPipelines,
  directories,
  userProfiles,
} from '~/db';
import { DelegatedAccessInfoDto } from './delegated-access-info.dto';

@Injectable()
export class GetDirectoryDelegatedAccessQuery {
  public constructor(
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public async run(userProfileId: string): Promise<DelegatedAccessInfoDto[]> {
    if (this.config.delegatedAccessScan === 'disabled') {
      return [];
    }

    const directoriesIgnoredForSync = this.db
      .selectDistinct({ microsoftDirectoryId: directories.providerDirectoryId })
      .from(directories)
      .where(eq(directories.ignoreForSync, true));

    return await this.db
      .select({
        ownerUserEmail: sql<string>`${userProfiles.email}`,
        ownerUserId: delegatedAccessPipelines.ownerUserId,
        ownerProviderUserId: sql<string>`${userProfiles.providerUserId}`,
        msGraphDirectoryIds: sql<string[]>`array_agg(${delegatedAccessDirectories.directoryId})`,
      })
      .from(delegatedAccessPipelines)
      .innerJoin(
        delegatedAccessDirectories,
        eq(delegatedAccessPipelines.id, delegatedAccessDirectories.pipelineId),
      )
      .innerJoin(userProfiles, eq(delegatedAccessPipelines.ownerUserId, userProfiles.id))
      .where(
        and(
          eq(delegatedAccessPipelines.hasFullDelegatedAccess, false),
          eq(delegatedAccessPipelines.delegateUserId, userProfileId),
          isNotNull(userProfiles.providerUserId),
          isNotNull(userProfiles.email),
          notInArray(delegatedAccessDirectories.directoryId, directoriesIgnoredForSync),
        ),
      )
      .groupBy(
        userProfiles.providerUserId,
        userProfiles.email,
        delegatedAccessPipelines.ownerUserId,
      );
  }
}
