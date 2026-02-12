import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq, inArray, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import {
  DirectoryType,
  DRIZZLE,
  DrizzleDatabase,
  directories,
  SystemDirectoriesIgnoredForSync,
} from '~/drizzle';
import { GetSubscriptionAndUserProfileQuery } from '../subscription-utils/get-subscription-and-user-profile.query';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { GraphOutlookDirectory } from './microsoft-graph.dtos';

const USER_DIRECTORY_TYPE = 'User Defined Directory' as DirectoryType;

@Injectable()
export class SyncDirectoriesCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly fetchAllDirectoriesFromOutlookQuery: FetchAllDirectoriesFromOutlookQuery,
    private readonly getSubscriptionAndUserProfileQuery: GetSubscriptionAndUserProfileQuery,
  ) {}

  @Span()
  public async run(subscriptionId: string): Promise<void> {
    const { userProfile } = await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);

    const microsoftDirectories = await this.fetchAllDirectoriesFromOutlookQuery.run(userProfile.id);

    await this.upsertDirectories({
      userProfileId: userProfile.id,
      microsoftDirectories,
    });
    const { idsToDeleteInDatabase, providerParentIdsToDeleteInUnique } =
      await this.getDirectoriesToRemove({
        userProfileId: userProfile.id,
        microsoftDirectories,
      });
    await this.db.delete(directories).where(inArray(directories.id, idsToDeleteInDatabase));
    for (const _id of providerParentIdsToDeleteInUnique) {
      // TODO: Call unique to delete all meta keys with values in providerParentIdsToDeleteInUnique
    }
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

  private async getDirectoriesToRemove({
    userProfileId,
    microsoftDirectories,
  }: {
    userProfileId: string;
    microsoftDirectories: GraphOutlookDirectory[];
  }): Promise<{
    idsToDeleteInDatabase: string[];
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

    while (queue.length) {
      providerParentIdsToDeleteInUnique.push(...queue.map((item) => item.providerDirectoryId));
      const parentIdsToIgnore = queue.map((item) => item.id);

      await this.db
        .update(directories)
        .set({ ignoreForSync: true })
        .where(inArray(directories.id, parentIdsToIgnore));
      queue = databaseDirectories.filter(
        (item) => item.parentId && parentIdsToIgnore.includes(item.parentId),
      );
    }

    return {
      idsToDeleteInDatabase: toDeleteInDatabase.map((item) => item.id),
      providerParentIdsToDeleteInUnique,
    };
  }
}
