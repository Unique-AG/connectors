import { Inject, Injectable } from "@nestjs/common";
import { Span, TraceService } from "nestjs-otel";
import {
  DRIZZLE,
  DrizzleDatabase,
  mailFolders,
  mailFoldersSync,
  UserProfile,
  userProfiles,
} from "~/drizzle";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import { UniqueService } from "~/unique/unique.service";
import {
  GraphMailFolder,
  graphMailFolderSchema,
} from "../microsoft-graph.dtos";
import { and, eq } from "drizzle-orm";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "../../../unique/fetch-or-create-outlook-emails-root-scope.command";
import assert from "node:assert";
import { isNonNullish } from "remeda";
import {
  isDrizzleDatabaseError,
  isDrizzleDuplicateFieldError,
} from "~/drizzle/isDrizzleError";

interface GraphFolderInfo {
  folder: GraphMailFolder;
  isDirectoryIgnoredForSync: boolean;
}

@Injectable()
export class SyncFoldersCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
    private readonly fetchOrCreateOutlookEmailsRootScopeCommand: FetchOrCreateOutlookEmailsRootScopeCommand,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute("user_profile_id", userProfileId.toString());
    span?.addEvent(`Start system folders sync`);
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile`);

    span?.addEvent(`Finished reading microsoft graph system directories`);

    const microsoftGraphDirectories = await this.fetchMicrosoftSystemFolders(
      userProfile.id,
    );
    await this.syncSystemFolders({
      microsoftGraphDirectories,
      userProfile,
    });

    span?.addEvent(`System folders sync finished`);
  }

  @Span()
  private async fetchMicrosoftSystemFolders(
    userProfileId: string,
  ): Promise<GraphFolderInfo[]> {
    const span = this.trace.getSpan();
    span?.setAttribute("user_profile_id", userProfileId.toString());
    const systemDirectories = [
      { apiName: "archive", isDirectoryIgnoredForSync: false },
      { apiName: "deleteditems", isDirectoryIgnoredForSync: true },
      { apiName: "drafts", isDirectoryIgnoredForSync: false },
      { apiName: "inbox", isDirectoryIgnoredForSync: false },
      { apiName: "junkemail", isDirectoryIgnoredForSync: true },
      { apiName: "outbox", isDirectoryIgnoredForSync: false },
      { apiName: "sentitems", isDirectoryIgnoredForSync: false },
      { apiName: "conversationhistory", isDirectoryIgnoredForSync: false },
      // TODO: This are system folders but are not returned by me/mailFolders => I'm not sure what I should do with those.
      {
        apiName: "recoverableitemsdeletions",
        isDirectoryIgnoredForSync: true,
      },
      { apiName: "clutter", isDirectoryIgnoredForSync: true },
    ];
    span?.addEvent(`Start fetching system directories from microsoft graph`);
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const microsoftGraphDirectories: GraphFolderInfo[] = [];
    for (const { apiName, isDirectoryIgnoredForSync } of systemDirectories) {
      const folderResponse = await client.api(`mailFolders/${apiName}`).get();
      microsoftGraphDirectories.push({
        folder: graphMailFolderSchema.parse(folderResponse),
        isDirectoryIgnoredForSync,
      });
    }
    span?.addEvent(`Finish fetching system directories from microsoft graph`);
    return microsoftGraphDirectories;
  }

  @Span()
  private async syncSystemFolders({
    microsoftGraphDirectories,
    userProfile,
  }: {
    userProfile: UserProfile;
    microsoftGraphDirectories: GraphFolderInfo[];
  }): Promise<void> {
    assert.ok(userProfile.email, `Missing user email: ${userProfile.id}`);
    const rootScope = await this.fetchOrCreateOutlookEmailsRootScopeCommand.run(
      userProfile.email,
    );
    const scopesToDeleteInCaseOfFailure: { id: string }[] = [];
    const [foldersSyncStatus] = await this.db
      .select()
      .from(mailFoldersSync)
      .where(eq(mailFoldersSync.userProfileId, userProfile.id))
      .execute();

    if (foldersSyncStatus?.systemFoldersSyncedAt) {
      // We already syncronized the system folders.
      return;
    }

    for (const {
      folder,
      isDirectoryIgnoredForSync,
    } of microsoftGraphDirectories) {
      const currentFolder = await this.db.query.mailFolders.findFirst({
        where: and(
          eq(mailFolders.userProfileId, userProfile.id),
          eq(mailFolders.microsoftId, folder.id),
        ),
      });

      if (isNonNullish(currentFolder)) {
        continue;
      }

      // TODO: create directory in rootScope
      const uniqueScopeId = `some_scope_id`;
      // Do we treat our service as some thing which can fail
      // If yes how we handle it ? Do I insert hald and go on later with the other half ?
      scopesToDeleteInCaseOfFailure.push({ id: uniqueScopeId });

      try {
        await this.db.insert(mailFolders).values({
          debugData: folder,
          displayName: folder.displayName,
          microsoftId: folder.id,
          isSystemFolder: true,
          isDirectoryIgnoredForSync,
          uniqueScopeId,
          userProfileId: userProfile.id,
          parentId: null,
        });
      } catch (error) {
        if (isDrizzleDuplicateFieldError(error)) {
          // TODO: Delete previous scope.
        }
      }
    }

    await this.db
      .update(mailFoldersSync)
      .set({ systemFoldersSyncedAt: new Date() })
      .where(eq(mailFoldersSync.userProfileId, userProfile.id))
      .execute();
  }
}
