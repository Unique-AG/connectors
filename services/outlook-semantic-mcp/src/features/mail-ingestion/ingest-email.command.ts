import assert from 'node:assert';
import { ContentMetadata, UniqueApiClient, UniqueOwnerType } from '@unique-ag/unique-api';
import { createSmeared } from '@unique-ag/utils';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Bottleneck from 'bottleneck';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish, omit } from 'remeda';
import { errors } from 'undici';
import { UniqueConfigNamespaced } from '~/config';
import { DirectoryType, DRIZZLE, DrizzleDatabase, directories, userProfiles } from '~/db';
import { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UploadFileForIngestionCommand } from '~/unique/upload-file-for-ingestion.command';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { GetFolderPathsQuery } from '../directories-sync/get-folder-paths.query';
import { UpsertDirectoryCommand } from '../directories-sync/upsert-directory.command';
import { GraphMessage } from './dtos/microsoft-graph.dtos';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage, MessageMetadata } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';
import { shouldSkipEmail } from './utils/should-skip-email';

const MAX_RETRIES = 3;
const BASE_BACKOFF_MS = 500;

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

export type MessageIngestionResult =
  | 'ingested'
  | 'skipped'
  | 'skipped-content-unchanged-already-ingested'
  | 'metadata-updated';

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
    private readonly getFolderPathsQuery: GetFolderPathsQuery,
  ) {}

  public async run({
    userProfileId,
    messageId,
    filters,
  }: {
    userProfileId: string;
    messageId: string;
    filters?: InboxConfigurationMailFilters;
  }): Promise<MessageIngestionResult | 'failed'> {
    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        return await this.processEmail({ userProfileId, messageId, filters });
      } catch (error) {
        if (attempt >= MAX_RETRIES) {
          // On last attempt we decide if we need to rethrow the error.
          const isMicrosoftRateLimit = error instanceof GraphError && error.statusCode === 429;
          const isUniqueRateLimit =
            error instanceof errors.ResponseError && error.statusCode === 429;
          const isBottleneckRateLimit = error instanceof Bottleneck.BottleneckError;
          // If it's a rate limit error we can stop the process of ingestion because trying again will not fix the issue
          if (isBottleneckRateLimit || isMicrosoftRateLimit || isUniqueRateLimit) {
            throw error;
          }
        }

        this.logger.warn({
          err: error,
          userProfileId,
          messageId,
          attempt,
          msg: `Ingestion attempt ${attempt}/${MAX_RETRIES} failed`,
        });
        if (attempt < MAX_RETRIES) {
          await this.sleep(BASE_BACKOFF_MS * 2 ** (attempt - 1));
        }
      }
    }
    this.logger.error({
      userProfileId,
      messageId,
      msg: `Ingestion failed after ${MAX_RETRIES} retries`,
    });
    return 'failed';
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  @Span()
  private async processEmail({
    userProfileId,
    messageId,
    filters,
  }: {
    userProfileId: string;
    messageId: string;
    filters?: InboxConfigurationMailFilters;
  }): Promise<MessageIngestionResult> {
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
    const fileKey = getUniqueKeyForMessage(userProfile.email, graphMessage);
    const files = await this.uniqueApi.files.getByKeys([fileKey]);
    const file = files.at(0);

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
        if (file) {
          await this.uniqueApi.files.delete(file.id);
        }
        return 'skipped';
      }
    }

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

    const folderPaths = await this.getFolderPathsQuery.run(userProfileId);
    const currentFolderPath =
      folderPaths[graphMessage.parentFolderId] ?? `/${parentDirectory.displayName}`;
    const metadata = getMetadataFromMessage(graphMessage, currentFolderPath);

    logContext.parentDirectoryIgnoredForSync = parentDirectory.ignoreForSync ?? false;
    logContext.parentDirectoryType = parentDirectory.internalType;
    traceAttrs(logContext);

    if (parentDirectory.ignoreForSync) {
      this.logger.log({ ...logContext, msg: `Parent directory ignored for sync` });
      if (isNonNullish(file)) {
        this.logger.debug({ ...logContext, msg: `Delete file from unique` });
        await this.uniqueApi.files.delete(file.id);
      }
      return 'skipped';
    }

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(userProfile.providerUserId),
    );
    assert.ok(rootScope, `Parent scope id`);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const emailMovedFolders =
      isNonNullish(file) && file.metadata?.emailProviderFolderPath !== currentFolderPath;

    if (
      isNonNullish(file) &&
      metadata.sentDateTime === file.metadata?.sentDateTime &&
      !emailMovedFolders
    ) {
      if (metadata.lastModifiedDateTime === file.metadata?.lastModifiedDateTime) {
        this.logger.log({
          ...logContext,
          msg: `Skip Update reason: Last modified date not changed`,
        });
        return 'skipped-content-unchanged-already-ingested';
      }
      this.logger.log({ ...logContext, msg: `Update file metadata` });
      await this.uniqueApi.ingestion.updateMetadata({
        contentId: file.id,
        // ContentMetadata value is Record<x, y> and metadata is an interface we do the type casting
        // here because you cannot assign an interface to a record.
        metadata: metadata as unknown as ContentMetadata,
      });
      return 'metadata-updated';
    }

    await this.uploadEmail({
      fileKey,
      metadata,
      rootScopeId: rootScope.id,
      graphMessage,
      messageId,
      client,
      logContext,
    });
    return 'ingested';
  }

  @Span()
  private async uploadEmail({
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
      this.logger.debug({ ...logContext, msg: `File Upload: Started` });
      const emailBuffer = await this.getEmlFile({ messageId, client });
      await this.uploadFileForIngestionCommand.run({
        uploadUrl: content.writeUrl,
        content: emailBuffer,
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

  private async getEmlFile({
    messageId,
    client,
  }: {
    messageId: string;
    client: Client;
  }): Promise<Buffer> {
    const emlStream = (await client
      .api(`me/messages/${messageId}/$value`)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .getStream()) as ReadableStream<Uint8Array<ArrayBuffer>>;

    // Unfortunately we have to take all the chunks in memory because the request to
    // Microsoft returns only the following headers:
    // ===============
    // cache-control: private
    // content-type: text/plain
    // strict-transport-security: max-age=31536000
    // request-id: 82e0492b-0659-4ee9-b3c2-c4d5b0341f85
    // client-request-id: 711d6458-b1bb-6caf-236f-1720ce107c15
    // x-ms-ags-diagnostic: {"ServerInfo":{"DataCenter":"Poland Central","Slice":"E","Ring":"2","ScaleUnit":"002","RoleInstance":"WA3PEPF000004A1"}}
    // access-control-allow-origin: *
    // access-control-expose-headers: ETag, Location, Preference-Applied, Content-Range,
    //   request-id, client-request-id, ReadWriteConsistencyToken, Retry-After, SdkVersion,
    //   WWW-Authenticate, x-ms-client-gcc-tenant, X-Planner-Operationid,
    //   x-ms-permissions-recommendations
    // ===============
    // There is no `Transfer-Encoding: chunked` and no `Content-Length`, which means the
    // response uses connection-close framing — the server sends the entire email body and
    // then closes the TCP connection. The full content is delivered in one shot, but you
    // can't know the size until the last byte arrives and the connection closes.
    // The Azure upload API requires Content-Length up front, so there's no point running
    // through the stream again just to count bytes.
    // IMPORTANT NOTE REGARDING MEMORY CONSUMPTION: With prefetch=7, up to 7 emails could be
    // buffered simultaneously per queues adding up to ~280MB of additional memory
    // (7 × 34MB max EML size) for every queue which processes emails. Since right now we have
    // 2 queues processing emails this means we add an additional ~476MB mb just from the email
    // transfer alose if we set the prefetch count to 7. The pod memory limit is 1Gi so we
    // should monitor heap usage closely.
    const chunks: Buffer[] = [];
    for await (const chunk of emlStream) {
      chunks.push(Buffer.from(chunk));
    }
    return Buffer.concat(chunks);
  }
}
