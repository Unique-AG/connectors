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
import { eq } from "drizzle-orm";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "./fetch-or-create-outlook-emails-root-scope.command";
import assert from "node:assert";

@Injectable()
export class SyncFoldersCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
    private readonly uniqueService: UniqueService,
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

    const systemDirectories = [
      "inbox",
      "sentitems",
      "drafts",
      "deleteditems",
      "junkemail",
      "archive",
      "outbox",
      "recoverableitemsdeletions",
      "clutter",
      "conversationhistory",
    ];
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const microsoftGraphDirectories: GraphMailFolder[] = [];
    for (const directory of systemDirectories) {
      const folderResponse = await client.api(`mailFolders/${directory}`).get();
      microsoftGraphDirectories.push(
        graphMailFolderSchema.parse(folderResponse),
      );
    }
    span?.addEvent(`Finished reading microsoft graph system directories`);

    await this.syncSystemFolders({
      microsoftGraphDirectories,
      userProfile,
    });

    span?.addEvent(`System folders sync finished`);
  }

  private async syncSystemFolders({
    microsoftGraphDirectories,
    userProfile,
  }: {
    userProfile: UserProfile;
    microsoftGraphDirectories: GraphMailFolder[];
  }): Promise<void> {
    assert.ok(userProfile.email, `Missing user email: ${userProfile.id}`);
    const rootScope = await this.fetchOrCreateOutlookEmailsRootScopeCommand.run(
      userProfile.email,
    );
    const scopesToDeleteInCaseOfFailure: { id: string }[] = [];
    await this.db.transaction(async (tx) => {
      const [foldersSyncStatus] = await tx
        .select()
        .from(mailFoldersSync)
        .where(eq(mailFoldersSync.userProfileId, userProfile.id))
        .for("update")
        .execute();

      if (foldersSyncStatus?.systemFoldersSyncedAt) {
        return;
      }

      for (const folder of microsoftGraphDirectories) {
        // TODO: create directory in rootScope
        const uniqueScopeId = `some_scope_id`;
        // Do we treat our service as some thing which can fail
        // If yes how we handle it ? Do I insert hald and go on later with the other half ?
        scopesToDeleteInCaseOfFailure.push({ id: uniqueScopeId });

        await tx.insert(mailFolders).values({
          debugData: folder,
          displayName: folder.displayName,
          microsoftId: folder.id,
          isSystemFolder: true,
          uniqueScopeId,
          userProfileId: userProfile.id,
          parentId: null,
        });
      }

      await tx
        .update(mailFoldersSync)
        .set({ systemFoldersSyncedAt: new Date() })
        .where(eq(mailFoldersSync.userProfileId, userProfile.id))
        .execute();
    });
  }
}
