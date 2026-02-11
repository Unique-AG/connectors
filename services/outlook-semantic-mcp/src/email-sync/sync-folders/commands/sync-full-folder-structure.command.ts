import { Inject, Injectable } from "@nestjs/common";
import { and, eq, not, notInArray } from "drizzle-orm";
import { Span } from "nestjs-otel";
import assert from "node:assert";
import { isNullish } from "remeda";
import {
  DRIZZLE,
  DrizzleDatabase,
  MailFolder,
  mailFolders,
  userProfiles,
} from "~/drizzle";
import { GraphMailFolder } from "../microsoft-graph.dtos";
import { FetchAllFodlersFromMicrosoftGraphQuery } from "./fetch-all-folders-from-microsoft-graph.query";
import { UniqueScopesService } from "~/unique/unique-scopes/unique-scopes.service";
import {
  FetchOrCreateOutlookEmailsRootScopeCommand,
  getRootScopePath,
} from "~/unique/unique-scopes/fetch-or-create-outlook-emails-root-scope.command";

@Injectable()
export class SyncFullFolderStructureCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly fetchAllFodlersFromMicrosoftGraphQuery: FetchAllFodlersFromMicrosoftGraphQuery,
    private uniqueScopesService: UniqueScopesService,
    private fetchOrCreateOutlookEmailsRootScopeCommand: FetchOrCreateOutlookEmailsRootScopeCommand,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<void> {
    const graphDirectories =
      await this.fetchAllFodlersFromMicrosoftGraphQuery.run(userProfileId);
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile`);
    assert.ok(
      userProfile.email,
      `User Profile: ${userProfile.id} without email`,
    );

    const graphDirectoryIds = await this.addMissingMicrosoftFoldersToDatabase({
      userProfile: { email: userProfile.email, id: userProfile.id },
      // allDirectoriesInDatabase,
      graphDirectories,
    });
    await this.removeExtraDirectories({ userProfileId, graphDirectoryIds });
  }

  private async addMissingMicrosoftFoldersToDatabase({
    userProfile,
    graphDirectories,
  }: {
    graphDirectories: GraphMailFolder[];
    userProfile: { email: string; id: string };
  }): Promise<string[]> {
    const allDirectoriesInDatabase = await this.db.query.mailFolders.findMany({
      where: eq(mailFolders.userProfileId, userProfile.id),
    });
    const microsoftIdToDatabaseRecord = allDirectoriesInDatabase.reduce<
      Record<string, MailFolder>
    >((acc, item) => {
      acc[item.microsoftId] = item;
      return acc;
    }, {});
    const microsoftFolderIdsIgnoredForSync = new Set(
      allDirectoriesInDatabase
        .filter((item) => item.isDirectoryIgnoredForSync)
        .map((item) => item.microsoftId),
    );

    // uniqueScopesService
    const rootScope = await this.fetchOrCreateOutlookEmailsRootScopeCommand.run(
      userProfile.email,
    );

    // TODO: Think if we can generate the whole scopes on paths -> and then maybe just update the db ?
    // Once we have all the paths go and update the db
    // My main concern is -> if the db fails or query to unique service fails what do we do ? The directories will remain in an inconcistent state
    // -> Maybe we need a job to cleanup dangling things ? Is the unique service done properly on paths for exaple not creating the same path twice in a folder ?
    let queue = graphDirectories.map((folder) => ({
      folder,
      parentScopeId: rootScope.id,
      path: [getRootScopePath(userProfile.email)],
      isDirectoryIgnoredForSync: microsoftFolderIdsIgnoredForSync.has(
        folder.id,
      ),
    }));
    let level = 0;
    const graphDirectoryIds: string[] = [];
    while (queue.length > 0) {
      const nextQueue: {
        folder: GraphMailFolder;
        parentScopeId: string;
        path: string[];
        isDirectoryIgnoredForSync: boolean;
      }[] = [];

      for (const {
        folder,
        parentScopeId,
        isDirectoryIgnoredForSync,
        path,
      } of queue) {
        graphDirectoryIds.push(folder.id);

        const doesDirectoryExist = folder.id in microsoftIdToDatabaseRecord;
        const newPath = [...path, folder.displayName];

        if (!doesDirectoryExist) {
          const [newScope] =
            await this.uniqueScopesService.createScopesBasedOnPaths([
              newPath.join("/"),
              folder.displayName,
            ]);
          assert.ok(newScope, `Could not create new scope on path`);
          await this.uniqueScopesService.updateScopeExternalId(
            newScope.id,
            folder.id,
          );
          // const uniqueScopeId = `SOME_SCOPE`;
          // TODO: Create scope in parent scope.

          const [newDirectory] = await this.db
            .insert(mailFolders)
            .values({
              debugData: folder,
              displayName: folder.displayName,
              microsoftId: folder.id,
              isSystemFolder: true,
              uniqueScopeId: newScope.id,
              userProfileId: userProfile.id,
              isDirectoryIgnoredForSync,
              parentId: null,
            })
            .returning();
          assert.ok(newDirectory, `Failed to insert directory: ${folder.id}`);
          microsoftIdToDatabaseRecord[folder.id] = newDirectory;
          const children = folder.childFolders ?? [];
          children.forEach((child) =>
            nextQueue.push({
              folder: child,
              parentScopeId: newScope.id,
              path: newPath,
              isDirectoryIgnoredForSync:
                isDirectoryIgnoredForSync ||
                microsoftFolderIdsIgnoredForSync.has(child.id),
            }),
          );
          continue;
        }

        const dbRecord = microsoftIdToDatabaseRecord[folder.id];
        assert.ok(dbRecord, `Failed to find directory: ${folder.id}`);
        const currentMicrosoftParentId =
          level === 0 ? null : folder.parentFolderId;
        const databaseMicrosoftParentId = dbRecord.parentId
          ? microsoftIdToDatabaseRecord[dbRecord.parentId]?.microsoftId
          : null;

        // Directory was moved
        if (currentMicrosoftParentId === databaseMicrosoftParentId) {
          await this.uniqueScopesService.updateScopeParent(
            dbRecord.uniqueScopeId,
            parentScopeId,
          );
          await this.uniqueScopesService.updateScopeExternalId(
            dbRecord.uniqueScopeId,
            folder.id,
          );

          dbRecord.parentId = isNullish(currentMicrosoftParentId)
            ? null
            : microsoftIdToDatabaseRecord[currentMicrosoftParentId]!.id;

          await this.db
            .update(mailFolders)
            .set({ parentId: dbRecord.parentId })
            .where(eq(mailFolders.id, dbRecord.id));
        }

        const children = folder.childFolders ?? [];
        children.forEach((child) =>
          nextQueue.push({
            folder: child,
            parentScopeId: dbRecord.uniqueScopeId,
            path: newPath,
            isDirectoryIgnoredForSync:
              isDirectoryIgnoredForSync ||
              microsoftFolderIdsIgnoredForSync.has(child.id),
          }),
        );
      }
      level++;
      queue = nextQueue;
    }

    return graphDirectoryIds;
  }

  private async removeExtraDirectories({
    userProfileId,
    graphDirectoryIds,
  }: {
    userProfileId: string;
    graphDirectoryIds: string[];
  }): Promise<void> {
    await this.db
      .delete(mailFolders)
      .where(
        and(
          eq(mailFolders.userProfileId, userProfileId),
          not(mailFolders.isSystemFolder),
          notInArray(mailFolders.microsoftId, graphDirectoryIds),
        ),
      );
  }
}
