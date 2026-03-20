import assert from 'node:assert';
import { ContentMetadata, UniqueApiClient, UniqueOwnerType } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish, omit } from 'remeda';
import { UniqueConfigNamespaced } from '~/config';
import { DirectoryType, DRIZZLE, DrizzleDatabase, directories, userProfiles } from '~/db';
import { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UploadFileForIngestionCommand } from '~/unique/upload-file-for-ingestion.command';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { UpsertDirectoryCommand } from '../directories-sync/upsert-directory.command';
import { GraphMessage } from './dtos/microsoft-graph.dtos';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage, MessageMetadata } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';
import { shouldSkipEmail } from './utils/should-skip-email';

type LogContext = Partial<{
  messageId: string;
  userProfileId: string;
  userEmail: string;
  uniqueFileId: string;
  key: string;
  parentDirectoryId: string;
  parentDirectoryIgnoredForSync: boolean;
  parentDirectoryType: DirectoryType;
  uniqueContentId: string;
  uniqueWriteUrl: string;
}>;

@Injectable()
export class IngestEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getMessageDetailsQuery: GetMessageDetailsQuery,
    private readonly uploadFileForIngestionCommand: UploadFileForIngestionCommand,
    private readonly upsertDirectoryCommand: UpsertDirectoryCommand,
  ) {}

  @Span()
  public async run({
    userProfileId,
    messageId,
    filters,
  }: {
    userProfileId: string;
    messageId: string;
    filters?: InboxConfigurationMailFilters;
  }): Promise<void> {
    traceAttrs({ userProfileId: userProfileId, messageId: messageId });
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile missing for id: ${userProfileId}`);
    assert.ok(userProfile.email, `User Profile email missing for: ${userProfile.id}`);
    const graphMessage = await this.getMessageDetailsQuery.run({
      userProfileId: userProfile.id,
      messageId,
    });

    if (filters) {
      const skipResult = shouldSkipEmail(graphMessage, filters, { userProfileId });
      if (skipResult.skip) {
        const { reason, matchedPattern } = skipResult;
        traceEvent('email skipped by filter', { reason, matchedPattern, userProfileId });
        this.logger.log({
          messageId,
          userProfileId,
          reason,
          matchedPattern,
          msg: 'Email skipped by filter',
        });
        return;
      }
    }

    const metadata = getMetadataFromMessage(graphMessage);
    const fileKey = getUniqueKeyForMessage(userProfile.email, graphMessage);
    const files = await this.uniqueApi.files.getByKeys([fileKey]);
    const file = files.at(0);

    let parentDirectory = await this.db.query.directories.findFirst({
      where: eq(directories.providerDirectoryId, graphMessage.parentFolderId),
    });
    const logContext: LogContext = {
      messageId,
      userProfileId,
      userEmail: createSmeared(userProfile.email).toString(),
      key: fileKey,
      uniqueFileId: file?.id,
      parentDirectoryId: graphMessage.parentFolderId,
    };
    traceAttrs(logContext);

    if (isNullish(parentDirectory)) {
      this.logger.warn({ ...logContext, msg: `New directory detected during emails sync.` });
      // If the directory is missing we upsert it but the type of directory is a special directory type
      // which will force the directory sync scheduler to run a full sync.
      parentDirectory = await this.upsertDirectoryCommand.run({
        parentId: null,
        userProfileId,
        updateOnConflict: false,
        directory: {
          id: graphMessage.parentFolderId,
          displayName: `__Unknown Directory Name__`,
          type: 'Unknown Directory: Created during email ingestion',
        },
      });
    }

    logContext.parentDirectoryIgnoredForSync = parentDirectory.ignoreForSync ?? false;
    logContext.parentDirectoryType = parentDirectory.internalType;
    traceAttrs(logContext);

    if (parentDirectory.ignoreForSync) {
      this.logger.log({ ...logContext, msg: `Parent directory ignored for sync` });
      if (isNonNullish(file)) {
        this.logger.debug({ ...logContext, msg: `Delete file from unique` });
        await this.uniqueApi.files.delete(file.id);
      }
      return;
    }

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScope, `Parent scope id`);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    if (isNonNullish(file) && metadata.sentDateTime === file.metadata?.sentDateTime) {
      if (metadata.lastModifiedDateTime === file.metadata?.lastModifiedDateTime) {
        this.logger.log({
          ...logContext,
          msg: `Skip Update reason: Last modified date not changed`,
        });
        return;
      }
      this.logger.log({ ...logContext, msg: `Update file metadata` });
      await this.uniqueApi.ingestion.updateMetadata({
        contentId: file.id,
        // ContentMetadata value is Record<x, y> and metadata is an interface we do the type casting
        // here because you cannot assign an interface to a record.
        metadata: metadata as unknown as ContentMetadata,
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
      logContext,
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
    logContext,
  }: {
    client: Client;
    rootScopeId: string;
    graphMessage: GraphMessage;
    messageId: string;
    fileKey: string;
    metadata: MessageMetadata;
    logContext: LogContext;
  }): Promise<void> {
    this.logger.log({ ...logContext, msg: `File Ingestion Started` });
    traceEvent(`File Ingestion Started`);
    const createContentRequest = {
      key: fileKey,
      title: `${graphMessage.subject ?? '__empty-title__'} - ${graphMessage.id}.eml`,
      mimeType: `message/rfc822`,
      // We pass byteSize as 1 because if we do not pass it the register content request will
      // create the content but the content will not be visible in Knowledge base.
      byteSize: 1,
      // ContentMetadata value is Record<x, y> and metadata is an interface we do the type casting
      // here because you cannot assign an interface to a record.
      metadata: metadata as unknown as ContentMetadata,
      scopeId: rootScopeId,
      ownerType: UniqueOwnerType.Scope,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      storeInternally: this.configService.get('unique.storeInternally', { infer: true }),
    };
    this.logger.debug({ ...logContext, msg: `Register content: Started` });
    const content = await this.uniqueApi.ingestion.registerContent(createContentRequest);
    logContext.uniqueContentId = content.id;
    this.logger.debug({ ...logContext, msg: `Register content: Finished` });

    try {
      const contentLength = await this.getContentLength({ messageId, client });
      const contentStream = await this.getEmlFileStream({ messageId, client });
      this.logger.debug({ ...logContext, msg: `File Upload: Started` });
      await this.uploadFileForIngestionCommand.run({
        uploadUrl: content.writeUrl,
        // We read the content length consuming the stream because our upload email
        // fails without it and it expects it up front.
        contentLength,
        content: contentStream,
        mimeType: createContentRequest.mimeType,
      });
      this.logger.debug({ ...logContext, msg: `File Upload: Finished` });

      this.logger.debug({ ...logContext, msg: `Finalize Ingestion: Started` });
      await this.uniqueApi.ingestion.finalizeIngestion({
        ...omit(createContentRequest, ['byteSize']),
        fileUrl: content.readUrl,
        url: content.readUrl,
        baseUrl: graphMessage.webLink,
      });
      traceEvent(`File Ingestion Finished`);
      this.logger.debug({ ...logContext, msg: `Finalize Ingestion: Finished` });
    } catch (error) {
      this.logger.warn({
        ...logContext,
        msg: `Cleaning up registered content after ingestion failure`,
      });
      try {
        await this.uniqueApi.files.delete(content.id);
      } catch (cleanupError) {
        this.logger.error({
          ...logContext,
          err: cleanupError,
          msg: `Failed to clean up registered content`,
        });
      }
      throw error;
    }
  }

  private async getContentLength({
    messageId,
    client,
  }: {
    messageId: string;
    client: Client;
  }): Promise<number> {
    const emlFileStream = await this.getEmlFileStream({ messageId, client });
    let contentLength = 0;
    for await (const chunk of emlFileStream) {
      contentLength += chunk.length;
    }
    return contentLength;
  }

  private async getEmlFileStream({
    messageId,
    client,
  }: {
    messageId: string;
    client: Client;
  }): Promise<ReadableStream<Uint8Array<ArrayBuffer>>> {
    return (await client
      .api(`me/messages/${messageId}/$value`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .getStream()) as Promise<ReadableStream<Uint8Array<ArrayBuffer>>>;
  }
}
