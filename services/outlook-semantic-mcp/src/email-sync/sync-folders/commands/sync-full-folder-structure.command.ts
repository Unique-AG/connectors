import { Inject, Injectable } from "@nestjs/common";
import { TraceService } from "nestjs-otel";
import {
  DRIZZLE,
  DrizzleDatabase,
  MailFolder,
  mailFolders,
  mailFoldersSync,
  userProfiles,
} from "~/drizzle";
import { DrizzleTransaction } from "~/drizzle/drizzle.module";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import { UniqueService } from "~/unique/unique.service";
import { eq } from "drizzle-orm";
import {
  GraphMailFolder,
  graphMailFolderSchema,
  graphMailFoldersSchema,
} from "../microsoft-graph.dtos";
import { FetchAllFodlersFromMicrosoftGraphQuery } from "./fetch-all-folders-from-microsoft-graph.query";
import assert from "node:assert";
import { isNullish } from "remeda";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "./fetch-or-create-outlook-emails-root-scope.command";

@Injectable()
export class SyncFullFolderStructureCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
    private readonly uniqueService: UniqueService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly fetchOrCreateOutlookEmailsRootScopeCommand: FetchOrCreateOutlookEmailsRootScopeCommand,
    private readonly fetchAllFodlersFromMicrosoftGraphQuery: FetchAllFodlersFromMicrosoftGraphQuery,
  ) {}

  public async run(userProfileId: string): Promise<void> {
    const graphDirectories =
      await this.fetchAllFodlersFromMicrosoftGraphQuery.run(userProfileId);
    const allDirectoriesInDatabase = await this.db.query.mailFolders.findMany({
      where: eq(mailFolders.userProfileId, userProfileId),
    });
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile`);
    assert.ok(
      userProfile.email,
      `User Profile: ${userProfile.id} without email`,
    );

    const rootScope = await this.fetchOrCreateOutlookEmailsRootScopeCommand.run(
      userProfile.email,
    );

    const microsoftIdToDatabaseRecord = allDirectoriesInDatabase.reduce<
      Record<string, MailFolder>
    >((acc, item) => {
      acc[item.microsoftId] = item;
      return acc;
    }, {});
    const initialIds = allDirectoriesInDatabase.map(
      (directory) => directory.microsoftId,
    );
    const microsoftGraphIds: Set<string> = new Set();

    // TODO: Think if we can generate the whole scopes on paths -> and then maybe just update the db ?
    // Once we have all the paths go and update the db
    // My main concern is -> if the db fails or query to unique service fails what do we do ? The directories will remain in an inconcistent state
    // -> Maybe we need a job to cleanup dangling things ? Is the unique service done properly on paths for exaple not creating the same path twice in a folder ?
    let queue = graphDirectories.map((folder) => ({
      folder,
      parentScopeId: rootScope.id,
    }));
    let level = 0;
    while (queue.length > 0) {
      const nextQueue: { folder: GraphMailFolder; parentScopeId: string }[] =
        [];

      // awa
      for (const { folder, parentScopeId } of queue) {
        microsoftGraphIds.add(folder.id);
        // nextQueue.push(...(folder.childFolders ?? []));

        const doesDirectoryExist = folder.id in microsoftIdToDatabaseRecord;

        if (!doesDirectoryExist) {
          const uniqueScopeId = `SOME_SCOPE`;
          // TODO: Create scope in parent scope.

          const [newDirectory] = await this.db
            .insert(mailFolders)
            .values({
              debugData: folder,
              displayName: folder.displayName,
              microsoftId: folder.id,
              isSystemFolder: true,
              uniqueScopeId,
              userProfileId,
              parentId: null,
            })
            .returning();
          assert.ok(newDirectory, `Failed to insert directory: ${folder.id}`);
          microsoftIdToDatabaseRecord[folder.id] = newDirectory;
          const children = folder.childFolders ?? [];
          children.forEach((child) =>
            nextQueue.push({ folder: child, parentScopeId: uniqueScopeId }),
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
          // TODO: Unique -> move scope to parent scope
          // TODO: Update metadata request

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
          }),
        );
      }
      level++;
      queue = nextQueue;
    }
  }
}
