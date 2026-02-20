import { UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { and, count, eq, inArray, not } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { prop } from 'remeda';
import {
  DirectoryType,
  DRIZZLE,
  DrizzleDatabase,
  directories,
  directoriesSync,
  SystemDirectoriesIgnoredForSync,
} from '~/db';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { GraphOutlookDirectory } from './microsoft-graph.dtos';
import { SyncSystemDirectoriesForSubscriptionCommand } from './sync-system-driectories-for-subscription.command';
import { UpsertDirectoryCommand } from './upsert-directory.command';

const USER_DIRECTORY_TYPE: DirectoryType = 'User Defined Directory';

@Injectable()
export class SyncDirectoriesForSubscriptionCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly fetchAllDirectoriesFromOutlookQuery: FetchAllDirectoriesFromOutlookQuery,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly syncSystemDirectoriesCommand: SyncSystemDirectoriesForSubscriptionCommand,
    private readonly createRootScopeCommand: CreateRootScopeCommand,
    private readonly upsertDirectoryCommand: UpsertDirectoryCommand,
  ) {}

  @Span()
  public async run(userProfileTypeId: UserProfileTypeID): Promise<void> {
    traceAttrs({ user_profile_type_id: userProfileTypeId.toString() });
    const userProfile = await this.getUserProfileQuery.run(userProfileTypeId);
    await this.createRootScopeCommand.run({
      userProfileEmail: userProfile.email,
      userProviderUserId: userProfile.providerUserId,
    });

    const totalDirectories = await this.db
      .select({ count: count() })
      .from(directories)
      .where(eq(directories.userProfileId, userProfile.id))
      .execute();

    // We only sync the system directories once.
    if (!totalDirectories.length || totalDirectories.at(0)?.count === 0) {
      await this.syncSystemDirectoriesCommand.run(userProfileTypeId);
    }

    const microsoftDirectories = await this.fetchAllDirectoriesFromOutlookQuery.run(userProfile.id);

    await this.upsertDirectories({
      userProfileId: userProfile.id,
      microsoftDirectories,
    });

    await this.removeExtraDirectories({
      userProfileId: userProfile.id,
      providerUserId: userProfile.providerUserId,
      microsoftDirectories,
    });

    await this.db
      .update(directoriesSync)
      .set({ lastDirectorySyncRanAt: new Date() })
      .where(eq(directoriesSync.userProfileId, userProfile.id))
      .execute();
  }

  private async upsertDirectories({
    userProfileId,
    microsoftDirectories,
  }: {
    userProfileId: string;
    microsoftDirectories: GraphOutlookDirectory[];
  }): Promise<void> {
    let currentDirectoriesToProcess: {
      directory: GraphOutlookDirectory;
      parentId: null | string;
    }[] = microsoftDirectories.map((directory) => ({
      directory,
      parentId: null,
    }));

    // We traverse a graph from root level by level and upsert in our database the new nodes.
    while (currentDirectoriesToProcess.length) {
      const nextQueue = await Promise.all(
        currentDirectoriesToProcess.flatMap(({ parentId, directory }) =>
          this.updateDirectory({
            userProfileId,
            parentId,
            directory,
          }),
        ),
      );
      currentDirectoriesToProcess = nextQueue.flat();
    }
  }

  private async updateDirectory({
    parentId,
    userProfileId,
    directory,
  }: {
    parentId: string | null;
    userProfileId: string;
    directory: GraphOutlookDirectory;
  }): Promise<{ parentId: string | null; directory: GraphOutlookDirectory }[]> {
    const newDirectory = await this.upsertDirectoryCommand.run({
      parentId,
      userProfileId,
      directory: { ...directory, type: USER_DIRECTORY_TYPE },
      updateOnConflict: true,
    });
    return (
      directory.childFolders?.map((child) => ({
        parentId: newDirectory.id,
        directory: child,
      })) ?? []
    );
  }

  private async removeExtraDirectories({
    userProfileId,
    providerUserId,
    microsoftDirectories,
  }: {
    userProfileId: string;
    providerUserId: string;
    microsoftDirectories: GraphOutlookDirectory[];
  }) {
    const { idsToDeleteInDatabase, providerParentIdsToDeleteInUnique, ignoredDirectoryIds } =
      await this.getDirectoriesToRemove({
        userProfileId,
        microsoftDirectories,
      });
    await this.db
      .delete(directories)
      .where(
        and(
          eq(directories.userProfileId, userProfileId),
          // This condition is already enforced but we double enforce it on the delete statement.
          eq(directories.internalType, 'User Defined Directory'),
          inArray(directories.id, idsToDeleteInDatabase),
        ),
      )
      .execute();

    await this.db
      .update(directories)
      .set({ ignoreForSync: true })
      .where(
        and(
          eq(directories.userProfileId, userProfileId),
          inArray(directories.id, ignoredDirectoryIds),
        ),
      )
      .execute();

    await this.db
      .update(directories)
      .set({ ignoreForSync: false })
      .where(
        and(
          eq(directories.userProfileId, userProfileId),
          not(inArray(directories.id, ignoredDirectoryIds)),
        ),
      )
      .execute();

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalId(providerUserId),
    );
    if (!rootScope) {
      return;
    }

    for (const providerDirectoryId of providerParentIdsToDeleteInUnique) {
      // TODO: check if we can avoid the scopeId and pass a record<string, stirng>
      const contentIds = await this.uniqueApi.files.getIdsByScopeAndMetadataKey(
        rootScope.id,
        'parentFolderId',
        providerDirectoryId,
      );
      if (contentIds.length) {
        await this.uniqueApi.files.deleteByIds(contentIds);
      }
    }
  }

  private async getDirectoriesToRemove({
    userProfileId,
    microsoftDirectories,
  }: {
    userProfileId: string;
    microsoftDirectories: GraphOutlookDirectory[];
  }): Promise<{
    // User defined directories which should be deleted in database.
    idsToDeleteInDatabase: string[];
    // All directories under the deleted items and other folders like junk email.
    ignoredDirectoryIds: string[];
    // All user defined directories which should be deleted in database or ignored for sync are here
    // basically we have to check them in unique.
    providerParentIdsToDeleteInUnique: string[];
  }> {
    const collectIdsRecurive = (directories: GraphOutlookDirectory[]): string[] => {
      return directories.flatMap((directory) => {
        return [directory.id, ...collectIdsRecurive(directory?.childFolders ?? [])];
      });
    };
    const currentDirectories = new Set(collectIdsRecurive(microsoftDirectories));

    const databaseDirectories = await this.db.query.directories.findMany({
      where: eq(directories.userProfileId, userProfileId),
    });
    const toDeleteInDatabase = databaseDirectories.filter(
      (item) =>
        // We only delete user defined directories
        item.internalType === USER_DIRECTORY_TYPE &&
        !currentDirectories.has(item.providerDirectoryId),
    );

    const providerParentIdsToDeleteInUnique = toDeleteInDatabase.map(
      (item) => item.providerDirectoryId,
    );

    const ignoredDirectoryIds = [];

    let directoriesIgnoredForSync = databaseDirectories.filter((item) =>
      SystemDirectoriesIgnoredForSync.includes(item.internalType),
    );

    while (directoriesIgnoredForSync.length) {
      providerParentIdsToDeleteInUnique.push(
        ...directoriesIgnoredForSync.map(prop('providerDirectoryId')),
      );
      const parentIdsToIgnore = directoriesIgnoredForSync.map((item) => item.id);
      directoriesIgnoredForSync = databaseDirectories.filter(
        (item) => item.parentId && parentIdsToIgnore.includes(item.parentId),
      );
      ignoredDirectoryIds.push(...parentIdsToIgnore);
    }

    return {
      idsToDeleteInDatabase: toDeleteInDatabase.map(prop('id')),
      ignoredDirectoryIds,
      providerParentIdsToDeleteInUnique,
    };
  }
}
