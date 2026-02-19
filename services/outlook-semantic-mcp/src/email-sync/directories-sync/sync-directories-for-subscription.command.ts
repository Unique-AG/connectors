import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { count, eq, inArray, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import {
  DirectoryType,
  DRIZZLE,
  DrizzleDatabase,
  directories,
  directoriesSync,
  SystemDirectoriesIgnoredForSync,
} from '~/drizzle';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { GraphOutlookDirectory } from './microsoft-graph.dtos';
import { SyncSystemDirectoriesForSubscriptionCommand } from './sync-system-driectories-for-subscription.command';

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
      .where(eq(directories.userProfileId, userProfile.id));

    // Normally it should not happen but we want to be sure we have the system directories correctly defined first.
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
      .set({ lastDirectorySyncRunnedAt: new Date() })
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
    let queue: { directory: GraphOutlookDirectory; parentId: null | string }[] =
      microsoftDirectories.map((directory) => ({
        directory,
        parentId: null,
      }));

    while (queue.length) {
      const nextQueue = await Promise.all(
        queue.flatMap(({ parentId, directory }) =>
          this.updateDirectory({
            userProfileId,
            parentId,
            directory,
          }),
        ),
      );
      queue = nextQueue.flat();
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
    const newDirectories = await this.db
      .insert(directories)
      .values({
        userProfileId,
        parentId,
        displayName: directory.displayName,
        internalType: USER_DIRECTORY_TYPE,
        providerDirectoryId: directory.id,
      })
      .onConflictDoUpdate({
        target: [directories.userProfileId, directories.providerDirectoryId],
        set: {
          parentId: sql.raw(`excluded.${directories.parentId.name}`),
          displayName: sql.raw(`excluded.${directories.displayName.name}`),
        },
      })
      .returning();

    const newDirectory = newDirectories.at(0);
    assert.ok(newDirectory, `Counld not create new directory`);
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
    const {
      idsToDeleteInDatabase,
      providerParentIdsToDeleteInUnique,
      directoryIdsToMarkAsIgnored,
    } = await this.getDirectoriesToRemove({
      userProfileId,
      microsoftDirectories,
    });
    await this.db.delete(directories).where(inArray(directories.id, idsToDeleteInDatabase));

    await this.db
      .update(directories)
      .set({ ignoreForSync: true })
      .where(inArray(directories.id, directoryIdsToMarkAsIgnored));

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalId(providerUserId),
    );
    if (!rootScope) {
      return;
    }

    for (const providerDirectoryId of providerParentIdsToDeleteInUnique) {
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
    idsToDeleteInDatabase: string[];
    directoryIdsToMarkAsIgnored: string[];
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
        item.internalType === USER_DIRECTORY_TYPE &&
        !currentDirectories.has(item.providerDirectoryId),
    );
    let queue = databaseDirectories.filter((item) =>
      SystemDirectoriesIgnoredForSync.includes(item.internalType),
    );

    const providerParentIdsToDeleteInUnique = toDeleteInDatabase.map(
      (item) => item.providerDirectoryId,
    );

    const directoryIdsToMarkAsIgnored = [];

    while (queue.length) {
      providerParentIdsToDeleteInUnique.push(...queue.map((item) => item.providerDirectoryId));
      const parentIdsToIgnore = queue.map((item) => item.id);
      queue = databaseDirectories.filter(
        (item) => item.parentId && parentIdsToIgnore.includes(item.parentId),
      );
      directoryIdsToMarkAsIgnored.push(...parentIdsToIgnore);
    }

    return {
      idsToDeleteInDatabase: toDeleteInDatabase.map((item) => item.id),
      directoryIdsToMarkAsIgnored,
      providerParentIdsToDeleteInUnique,
    };
  }
}
