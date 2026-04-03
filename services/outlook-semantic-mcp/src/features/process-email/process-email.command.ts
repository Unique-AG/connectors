import assert from 'node:assert';
import {
  ContentMetadata,
  UniqueApiClient,
  UniqueFile,
  UniqueOwnerType,
} from '@unique-ag/unique-api';
import { Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { clone, isNonNullish, isNullish, omit } from 'remeda';
import { UniqueConfigNamespaced } from '~/config';
import { DRIZZLE, DrizzleDatabase, directories } from '~/db';
import { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UploadFileForIngestionCommand } from '~/unique/upload-file-for-ingestion.command';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { Nullish } from '~/utils/nullish';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '~/utils/source-kind-and-name';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';
import { UpsertDirectoryCommand } from '../directories-sync/upsert-directory.command';
import { GraphMessage } from './dtos/microsoft-graph.dtos';
import { getMetadataFromMessage, MessageMetadata } from './utils/get-metadata-from-message';
import { shouldSkipEmail } from './utils/should-skip-email';

export type MessageIngestionResult =
  | 'ingested'
  | 'skipped'
  | 'skipped-content-unchanged-already-ingested'
  | 'metadata-updated';

interface UserContext {
  email: Smeared;
  // user_profile.id in our database
  profileId: string;
  // provider_user_id in our daabase
  providerId: string;
}

export interface ProcessEmailCommandInput {
  client: Client;
  graphMessage: GraphMessage;
  fileKey: string;
  file: Nullish<UniqueFile>;
  user: UserContext;
  filters: InboxConfigurationMailFilters;
}

interface BaseLogContext extends Record<string, string | undefined | boolean> {
  messageId: string;
  internetId: string | undefined;
  userProfileId: string;
  providerUserId: string;
  userEmail: string;
}

@Injectable()
export class ProcessEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
    private readonly uploadFileForIngestionCommand: UploadFileForIngestionCommand,
    private readonly upsertDirectoryCommand: UpsertDirectoryCommand,
  ) {}

  @Span()
  public async run(input: ProcessEmailCommandInput): Promise<MessageIngestionResult | 'failed'> {
    return await withRetryAttempts({
      fn: () => {
        const logContext = {
          messageId: input.graphMessage.id,
          internetId: input.graphMessage.internetMessageId ?? undefined,
          userProfileId: input.user.profileId,
          providerUserId: input.user.providerId,
          userEmail: input.user.email.toString(),
        };
        return this.runProcessEmail({ ...input, baseLogContext: logContext });
      },
      onError: rethrowRateLimitError,
      getResultFailure: () => 'failed',
    });
  }

  @Span()
  private async runProcessEmail({
    graphMessage,
    file,
    fileKey,
    user,
    filters,
    client,
    baseLogContext,
  }: ProcessEmailCommandInput & {
    baseLogContext: BaseLogContext;
  }): Promise<MessageIngestionResult> {
    const metadata = getMetadataFromMessage(graphMessage);

    let parentDirectory = await this.db.query.directories.findFirst({
      where: eq(directories.providerDirectoryId, graphMessage.parentFolderId),
    });

    const logContext = clone(baseLogContext);

    if (filters) {
      const skipResult = shouldSkipEmail(graphMessage, filters, {
        userProfileId: user.profileId,
      });
      if (skipResult.skip) {
        if (file) {
          await this.deleteWithoutRetry(file.id, {
            ...logContext,
            additionalFailureMessage: `Deleting file skipped by filters failed`,
          });
        }

        const { reason, matchedPattern } = skipResult;
        const event = {
          name: 'Email skipped by filter',
          props: { ...logContext, reason, matchedPattern },
        };
        traceEvent(event.name, event.props);
        this.logger.log({ ...event.props, msg: event.name });
        return 'skipped';
      }
    }

    if (isNullish(parentDirectory)) {
      this.logger.warn({ ...logContext, msg: `New directory detected during emails sync.` });
      // If the directory is missing we upsert it but the type of directory is a special directory type
      // which will force the directory sync scheduler to run a full sync.
      parentDirectory = await this.upsertDirectoryCommand.run({
        parentId: null,
        userProfileId: user.profileId,
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
    traceAttrs({
      parentDirectoryIgnoredForSync: parentDirectory.ignoreForSync ?? false,
      parentDirectoryType: parentDirectory.internalType,
    });

    if (parentDirectory.ignoreForSync) {
      this.logger.log({ ...logContext, msg: `Parent directory ignored for sync` });
      if (isNonNullish(file)) {
        this.logger.debug({ ...logContext, msg: `Delete file from unique` });
        await this.deleteWithoutRetry(file.id, {
          ...logContext,
          additionalFailureMessage: `Deleting content from skipped foler failed`,
        });
      }
      return 'skipped';
    }

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalIdForUser(user.providerId),
    );
    assert.ok(rootScope, `Parent scope id`);

    // const client = this.graphClientFactory.createClientForUser(context.userProfileId);

    if (isNonNullish(file) && metadata.sentDateTime === file.metadata?.sentDateTime) {
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

    await this.uploadEmailForIngestion({
      fileKey,
      metadata,
      rootScopeId: rootScope.id,
      graphMessage,
      client,
      logContext,
    });
    return 'ingested';
  }

  @Span()
  private async uploadEmailForIngestion({
    client,
    rootScopeId,
    graphMessage,
    metadata,
    fileKey,
    logContext: logContextRaw,
  }: {
    client: Client;
    rootScopeId: string;
    graphMessage: GraphMessage;
    fileKey: string;
    metadata: MessageMetadata;
    logContext: {
      userProfileId: string;
      providerUserId: string;
      userEmail: string;
    };
  }): Promise<void> {
    // We will update the log context while we run.
    const logContext = clone(logContextRaw) as Record<string, string>;
    this.logger.debug({ ...logContext, msg: `Email Ingestion Started` });
    traceEvent(`Email Ingestion Started`);

    const createContentRequest = {
      key: fileKey,
      title: `${graphMessage.subject || ''}.eml`,
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
    traceEvent(`Content registered`, logContext);
    this.logger.debug({ ...logContext, msg: `Register content: Finished` });

    try {
      this.logger.debug({ ...logContext, msg: `File Upload: Started` });
      const emailBuffer = await this.getEmlFile({ messageId: graphMessage.id, client });
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
        err: error,
        msg: `Cleaning up registered content after ingestion failure`,
      });
      await this.deleteWithoutRetry(content.id, {
        ...logContext,
        additionalFailureMessage: `Delete registered content after ingestion failure failed`,
      });
      traceEvent('Email Ingestion Failed');
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

  private async deleteWithoutRetry(
    contentId: string,
    logContext: Record<string, string | undefined | boolean>,
  ): Promise<void> {
    try {
      await this.uniqueApi.files.delete(contentId);
    } catch (err) {
      if (isRateLimitError(err)) {
        throw err;
      }
      this.logger.warn({
        ...logContext,
        err,
        msg: `Failed to delete content with id: ${contentId}`,
      });
    }
  }
}
