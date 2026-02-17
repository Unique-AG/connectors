import assert from 'node:assert';
import { UniqueApiClient, UniqueOwnerType } from '@unique-ag/unique-api';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, directories, userProfiles } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { GraphMessage } from './dtos/microsoft-graph.dtos';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage, MessageMetadata } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';

@Injectable()
export class IngestEmailCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getMessageDetailsQuery: GetMessageDetailsQuery,
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
    assert.ok(userProfile.email, `User Profile email missing for: ${userProfile.id}`);
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

    // TODO tomorrow: Check with Michat
    // 1 - I need more details on file
    //     metadata
    // 2 - Register content isn't actually a content upsert why we force all parameters to be passed since they require just a few ?
    //     Can I use registerContent to upsert existing metadata

    if (
      isNullish(file) || // File does not exist
      metadata.sentDateTime !== file.metadata?.sentDateTime // File exists but the sentDateTime is different so we need to reigest everything.
    ) {
      await this.injestEmail({
        fileKey,
        metadata,
        rootScopeId: rootScope.id,
        graphMessage,
        messageId,
        client,
      });
      return;
    }

    await this.uniqueApi.ingestion.registerContent({
      key: fileKey,
      title: `${graphMessage.subject} - ${graphMessage.id}.eml`,
      mimeType: `message/rfc822`,
      // FROM where do we I get this thing ? I got just a readable stream from microsoft
      byteSize: file.byteSize,
      metadata: metadata,
      scopeId: rootScope.id,
      ownerType: UniqueOwnerType.User,
      sourceOwnerType: UniqueOwnerType.User,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      // TODO: Check with Michat
      storeInternally: false,
    });
  }

  private async injestEmail({
    client,
    rootScopeId,
    graphMessage,
    metadata,
    messageId,
    fileKey,
  }: {
    client: Client;
    rootScopeId: string;
    graphMessage: GraphMessage;
    messageId: string;
    fileKey: string;
    metadata: MessageMetadata;
  }): Promise<void> {
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
      scopeId: rootScopeId,
      ownerType: UniqueOwnerType.Scope,
      sourceOwnerType: UniqueOwnerType.Scope,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      // TODO: Check with Michat
      storeInternally: false,
    };

    const content = await this.uniqueApi.ingestion.registerContent(createContentRequest);

    let byteSize = 0;

    const transformedStream = response.pipeThrough(
      new TransformStream({
        transform: (chunk, controller) => {
          byteSize += chunk.length;
          controller.enqueue(chunk);
        },
      }),
    );

    await this.uniqueApi.ingestion.streamUpload({
      uploadUrl: content.writeUrl,
      mimeType: createContentRequest.mimeType,
      content: transformedStream,
    });

    await this.uniqueApi.ingestion.finalizeIngestion({
      key: fileKey,
      title: createContentRequest.title,
      mimeType: createContentRequest.mimeType,
      ownerType: createContentRequest.ownerType,
      byteSize: byteSize,
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
}
