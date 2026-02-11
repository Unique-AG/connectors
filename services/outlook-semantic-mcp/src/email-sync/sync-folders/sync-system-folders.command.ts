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
import { GraphMailFolder, graphMailFolderSchema } from "./microsoft-graph.dtos";
import { and, eq } from "drizzle-orm";
import { getRootScopePath } from "~/unique/unique-scopes/fetch-or-create-outlook-emails-root-scope.command";
import assert from "node:assert";
import { isNonNullish } from "remeda";
import { isDrizzleDuplicateFieldError } from "~/drizzle/isDrizzleError";
import { UniqueScopesService } from "~/unique/unique-scopes/unique-scopes.service";

interface GraphFolderInfo {
  folder: GraphMailFolder;
  isDirectoryIgnoredForSync: boolean;
}

@Injectable()
export class SyncFoldersCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
    private readonly uniqueScopeService: UniqueScopesService,
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
    const userEmail = userProfile.email;
    assert.ok(userEmail, `Missing user email: ${userProfile.id}`);
    const [foldersSyncStatus] = await this.db
      .select()
      .from(mailFoldersSync)
      .where(eq(mailFoldersSync.userProfileId, userProfile.id))
      .execute();

    if (foldersSyncStatus?.systemFoldersSyncedAt) {
      // We already syncronized the system folders.
      return;
    }

    const scopes = await this.uniqueScopeService.createScopesBasedOnPaths(
      microsoftGraphDirectories.map(
        ({ folder }) => `${getRootScopePath(userEmail)}/${folder.displayName}`,
      ),
    );

    for (let index = 0; index < microsoftGraphDirectories.length; index++) {
      const directoryInfo = microsoftGraphDirectories[index];
      assert.ok(
        directoryInfo,
        `Wrong index:${index} access for microsoftGraphDirectories: ${microsoftGraphDirectories.length}`,
      );
      const { folder, isDirectoryIgnoredForSync } = directoryInfo;
      const scope = scopes[index];
      assert.ok(
        scope,
        `Wrong index:${index} access for scopes: ${scopes.length}`,
      );
      await this.uniqueScopeService.updateScopeExternalId(scope.id, folder.id);
      const currentFolder = await this.db.query.mailFolders.findFirst({
        where: and(
          eq(mailFolders.userProfileId, userProfile.id),
          eq(mailFolders.microsoftId, folder.id),
        ),
      });

      if (isNonNullish(currentFolder)) {
        continue;
      }
      try {
        await this.db.insert(mailFolders).values({
          debugData: folder,
          displayName: folder.displayName,
          microsoftId: folder.id,
          isSystemFolder: true,
          isDirectoryIgnoredForSync,
          uniqueScopeId: scope.id,
          userProfileId: userProfile.id,
          parentId: null,
        });
      } catch (error) {
        if (isDrizzleDuplicateFieldError(error)) {
          await this.uniqueScopeService.deleteScope(scope.id);
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
