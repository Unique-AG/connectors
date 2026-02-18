import assert from 'node:assert';
import { UniqueApiClient, UniqueOwnerType } from '@unique-ag/unique-api';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, directories, userProfiles } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UploadFileForIngestionCommand } from '~/unique/upload-file-for-ingestion.command';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { GraphMessage } from './dtos/microsoft-graph.dtos';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage, MessageMetadata } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';

@Injectable()
export class IngestEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getMessageDetailsQuery: GetMessageDetailsQuery,
    private readonly uploadFileForIngestionCommand: UploadFileForIngestionCommand,
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

    if (isNonNullish(file) && metadata.sentDateTime === file.metadata?.sentDateTime) {
      await this.uniqueApi.ingestion.updateMetadata({
        contentId: file.id,
        metadata,
      });
      return;
    }

    await this.ingestEmail({
      fileKey,
      metadata,
      rootScopeId: rootScope.id,
      graphMessage,
      messageId,
      client,
    });
  }

  @Span()
  private async ingestEmail({
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
    const createContentRequest = {
      key: fileKey,
      title: `${graphMessage.subject} - ${graphMessage.id}.eml`,
      mimeType: `message/rfc822`,
      // We pass byteSize as 1 because if we do not pass it the register content request will
      // create the content but the content will not be visible in Knowledge base.
      byteSize: 1,
      metadata: metadata,
      scopeId: rootScopeId,
      ownerType: UniqueOwnerType.Scope,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      // TODO: MAKE A CONFIG FOR THIS.
      storeInternally: true,
    };

    const content = await this.uniqueApi.ingestion.registerContent(createContentRequest);

    this.logger.log(`Register content finished: ${content.id}`);

    const responseUntyped = await client
      .api(`me/messages/${messageId}/$value`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .getStream();
    const contentStream = responseUntyped as ReadableStream<Uint8Array<ArrayBuffer>>;
    const { byteSize } = await this.uploadFileForIngestionCommand.run({
      uploadUrl: content.writeUrl,
      content: contentStream,
      mimeType: createContentRequest.mimeType,
    });
    this.logger.log(`Stream Upload finished: ${content.id}, byteSize: ${byteSize}`);

    await this.uniqueApi.ingestion.finalizeIngestion({
      ...createContentRequest,
      byteSize: byteSize,
      fileUrl: content.readUrl,
      url: content.readUrl,
      baseUrl: graphMessage.webLink,
    });
    this.logger.log(`Ingestion finished: ${content.id}`);
  }
}
