import assert from "node:assert";
import { UniqueApiClient, UniqueOwnerType } from "@unique-ag/unique-api";
import { Inject, Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { eq } from "drizzle-orm";
import { Span } from "nestjs-otel";
import { isNonNullish, isNullish } from "remeda";
import { UniqueConfigNamespaced } from "~/config";
import { DRIZZLE, DrizzleDatabase, directories, userProfiles } from "~/drizzle";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import { getRootScopeExternalId } from "~/unique/get-root-scope-path";
import { InjectUniqueApi } from "~/unique/unique-api.module";
import {
  INGESTION_SOURCE_KIND,
  INGESTION_SOURCE_NAME,
} from "~/utils/source-kind-and-name";
import { GetMessageDetailsQuery } from "./get-message-details.query";
import { getMetadataFromMessage } from "./utils/get-metadata-from-message";
import { getUniqueKeyForMessage } from "./utils/get-unique-key-for-message";

@Injectable()
export class IngestEmailCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getMessageDetailsQuery: GetMessageDetailsQuery,
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
  ) {}

  @Span()
  public async run({
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
  }): Promise<void> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile missing for id: ${userProfileId}`);
    assert.ok(
      userProfile.email,
      `User Profile email missing for: ${userProfile.id}`,
    );
    const graphMessage = await this.getMessageDetailsQuery.run({
      userProfileId: userProfile.id,
      messageId,
    });

    const metadata = getMetadataFromMessage(graphMessage);
    const fileKey = getUniqueKeyForMessage(userProfile.email, graphMessage);
    // => Here do full file ingestion.
    const files = await this.uniqueApi.files.getByKeys([fileKey]);
    const file = files.at(0);

    const parentDirectory = await this.db.query.directories.findFirst({
      where: eq(directories.providerDirectoryId, graphMessage.parentFolderId),
    });

    // Parent directory should exist because once he connects we run a full directory sync. If it's not there
    // we thrust that the full sync will catch this email. TODO: Check with Michat if we should Throw error.
    if (!parentDirectory || parentDirectory.ignoreForSync) {
      if (isNonNullish(file)) {
        await this.uniqueApi.files.delete(file.id);
      }
      return;
    }

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalId(userProfile.providerUserId),
    );
    assert.ok(rootScope, `Parent scope id`);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    if (isNullish(file)) {
      const response = (await client
        .api(`me/messages/${messageId}/$value`)
        .header(`Prefer`, `IdType="ImmutableId"`)
        .getStream()) as ReadableStream<Uint8Array<ArrayBuffer>>;

      const createContentRequest = {
        key: fileKey,
        title: `${graphMessage.subject} - ${graphMessage.id}.eml`,
        mimeType: `message/rfc822`,
        // FROM where do we I get this thing ? I got just a readable stream from microsoft
        byteSize: 1,
        metadata: metadata,
        scopeId: rootScope.id,
        ownerType: UniqueOwnerType.User,
        sourceOwnerType: UniqueOwnerType.User,
        sourceKind: INGESTION_SOURCE_KIND,
        sourceName: INGESTION_SOURCE_NAME,
        // TODO: Check with Michat
        storeInternally: false,
      };

      const content =
        await this.uniqueApi.ingestion.registerContent(createContentRequest);

      // TODO: Injest the file in unique.
      this.uniqueApi.ingestion.streamUpload({
        uploadUrl: this.correctWriteUrl(content.writeUrl),
        mimeType: createContentRequest.mimeType,
        content: response,
      });

      await this.uniqueApi.ingestion.finalizeIngestion({
        key: fileKey,
        title: createContentRequest.title,
        mimeType: createContentRequest.mimeType,
        ownerType: createContentRequest.ownerType,
        byteSize: createContentRequest.byteSize,
        scopeId: createContentRequest.scopeId,
        sourceOwnerType: createContentRequest.sourceOwnerType,
        sourceName: createContentRequest.sourceName,
        sourceKind: createContentRequest.sourceKind,
        fileUrl: content.readUrl,
        url: content.readUrl,
        baseUrl: graphMessage.webLink,
        storeInternally: !isNullish(content.internallyStoredAt),
      });
    }

    // if (graphMessage.sentDateTime === file.)
    // TODO:
    // Compare sentDateTime - sentDateTime
    //    => if not equal reingest + metadata update
    //    => if equal => compare metadata and update
  }

  // HACK:
  // When running in internal auth mode, rewrite the writeUrl to route through the ingestion
  // service's scoped upload endpoint. This enables internal services to upload files without
  // requiring external network access (hairpinning).
  // Ideally we should fix this somehow in the service itself by using a separate property or make
  // writeUrl configurable, but for now this hack lets us avoid hairpinning issues in the internal
  // upload flows.
  private correctWriteUrl(writeUrl: string): string {
    const uniqueAuthMode = this.configService.get("unique.serviceAuthMode", {
      infer: true,
    });
    if (uniqueAuthMode === "external") {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get("key");
    assert.ok(key, "writeUrl is missing key parameter");

    const ingestionApiUrl = this.configService.get("unique.apiBaseUrl", {
      infer: true,
    });
    return `${ingestionApiUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
  }

  // !SECTION: Helpers
}
