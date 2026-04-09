import assert from 'node:assert';
import type { Readable } from 'node:stream';
import type {
  ContentRegistrationRequest,
  IngestionFinalizationRequest,
  UniqueApiClient,
} from '@unique-ag/unique-api';
import { createSmeared, elapsedSeconds } from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import { type Dispatcher, request } from 'undici';
import type { TenantConfig } from '../config';
import type { ConfluenceApiClient } from '../confluence-api';
import {
  getSourceKind,
  INGESTION_MIME_TYPE,
  OWNER_TYPE,
  SOURCE_OWNER_TYPE,
} from '../constants/ingestion.constants';
import type { Metrics } from '../metrics';
import type { DiscoveredAttachment, FetchedPage } from './sync.types';

export class IngestionService {
  private readonly logger = new Logger(IngestionService.name);
  private readonly sourceKind: string;
  private readonly sourceName: string;
  private readonly dispatcher: Dispatcher | undefined;

  public constructor(
    private readonly config: TenantConfig,
    private readonly tenantName: string,
    private readonly uniqueApiClient: UniqueApiClient,
    private readonly confluenceApiClient: ConfluenceApiClient,
    private readonly metrics: Metrics,
    dispatcher?: Dispatcher,
  ) {
    this.dispatcher = dispatcher;
    this.sourceKind = getSourceKind(this.config.confluence.instanceType);
    this.sourceName = this.config.confluence.baseUrl;
  }

  public async ingestPage(page: FetchedPage, scopeId: string): Promise<void> {
    if (!page.body) {
      this.logger.log({
        pageId: page.id,
        title: page.title,
        msg: 'Skipping page with empty body',
      });
      return;
    }

    let contentId: string | undefined;
    try {
      const htmlBuffer = Buffer.from(page.body, 'utf-8');
      const baseKey = `${page.spaceId}_${page.spaceKey}/${page.id}`;
      const key = this.config.ingestion.useV1KeyFormat ? baseKey : `${this.tenantName}/${baseKey}`;

      const registrationRequest = this.buildPageRegistrationRequest(
        page,
        key,
        htmlBuffer.byteLength,
        scopeId,
      );
      const registrationResponse =
        await this.uniqueApiClient.ingestion.registerContent(registrationRequest);
      contentId = registrationResponse.id;

      const uploadUrl = this.correctWriteUrl(registrationResponse.writeUrl);
      await this.uploadBuffer(uploadUrl, htmlBuffer, INGESTION_MIME_TYPE);

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse.readUrl,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);
    } catch (error) {
      this.logger.error({
        pageId: page.id,
        title: page.title,
        err: error,
        msg: 'Failed to ingest page, skipping',
      });
      if (contentId) {
        await this.cleanupFailedRegistration(contentId, { pageId: page.id, title: page.title });
      }
    }
  }

  public async ingestAttachment(attachment: DiscoveredAttachment, scopeId: string): Promise<void> {
    if (attachment.fileSize === 0) {
      this.logger.log({
        attachmentId: attachment.id,
        title: createSmeared(attachment.title),
        msg: 'Skipping zero-byte attachment',
      });
      return;
    }

    let stream: Readable | undefined;
    let contentId: string | undefined;
    try {
      const baseKey = `${attachment.spaceId}_${attachment.spaceKey}/${attachment.pageId}::${attachment.id}`;
      const key = this.config.ingestion.useV1KeyFormat ? baseKey : `${this.tenantName}/${baseKey}`;

      const registrationRequest = this.buildAttachmentRegistrationRequest(attachment, key, scopeId);
      const registrationResponse =
        await this.uniqueApiClient.ingestion.registerContent(registrationRequest);
      contentId = registrationResponse.id;

      const uploadUrl = this.correctWriteUrl(registrationResponse.writeUrl);
      stream = await this.confluenceApiClient.getAttachmentDownloadStream(
        attachment.id,
        attachment.pageId,
        attachment.downloadPath,
      );
      const uploadStartTime = Date.now();
      await this.uploadStream(uploadUrl, stream, attachment.mediaType, attachment.fileSize);
      this.metrics.recordAttachmentUploadDuration(elapsedSeconds(uploadStartTime));

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse.readUrl,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);
    } catch (error) {
      stream?.destroy();
      this.logger.error({
        attachmentId: attachment.id,
        title: createSmeared(attachment.title),
        err: error,
        msg: 'Failed to ingest attachment, skipping',
      });
      if (contentId) {
        await this.cleanupFailedRegistration(contentId, {
          attachmentId: attachment.id,
          title: createSmeared(attachment.title),
        });
      }
    }
  }

  private async cleanupFailedRegistration(
    contentId: string,
    logContext: Record<string, unknown>,
  ): Promise<void> {
    try {
      await this.uniqueApiClient.files.deleteByIds([contentId]);
      this.logger.warn({
        ...logContext,
        contentId,
        msg: 'Deleted orphaned content after failed ingestion',
      });
    } catch (error) {
      this.logger.error({
        ...logContext,
        contentId,
        err: error,
        msg: 'Failed to clean up orphaned content after failed ingestion',
      });
    }
  }

  public async deleteContentByKeys(contentKeys: string[]): Promise<number> {
    if (contentKeys.length === 0) {
      return 0;
    }

    try {
      const files = await this.uniqueApiClient.files.getByKeys(contentKeys);
      if (files.length === 0) {
        this.logger.warn({
          keyCount: contentKeys.length,
          msg: 'No content found for keys, nothing to delete',
        });
        return 0;
      }

      const contentIds = files.map((f) => f.id);
      const deletedCount = await this.uniqueApiClient.files.deleteByIds(contentIds);
      this.logger.log({
        requestedCount: contentKeys.length,
        resolvedCount: files.length,
        deletedCount,
        msg: 'Content deleted',
      });

      // TODO: recordContentDeleted is disabled until deleteByIds returns accurate success/failure
      // counts. Currently deleteByIds counts items sent, not items confirmed deleted by the API,
      // and on failure we don't know how many were partially deleted. Follow-up: fix deleteByIds
      // in @unique-ag/unique-api to return { deleted, failed } based on the mutation response.
      return deletedCount;
    } catch (error) {
      this.logger.error({ contentKeys, err: error, msg: 'Failed to delete content, skipping' });
      return 0;
    }
  }

  private buildPageRegistrationRequest(
    page: FetchedPage,
    key: string,
    byteSize: number,
    scopeId: string,
  ): ContentRegistrationRequest {
    return {
      key,
      title: page.title.value,
      mimeType: INGESTION_MIME_TYPE,
      ownerType: OWNER_TYPE,
      scopeId,
      sourceOwnerType: SOURCE_OWNER_TYPE,
      sourceKind: this.sourceKind,
      sourceName: this.sourceName,
      url: page.webUrl,
      baseUrl: this.config.confluence.baseUrl,
      byteSize,
      metadata: {
        confluenceLabels: page.metadata?.confluenceLabels ?? [],
        spaceKey: page.spaceKey,
        spaceName: page.spaceName,
      },
      storeInternally: this.config.ingestion.storeInternally,
    };
  }

  private buildAttachmentRegistrationRequest(
    attachment: DiscoveredAttachment,
    key: string,
    scopeId: string,
  ): ContentRegistrationRequest {
    return {
      key,
      title: attachment.title,
      mimeType: attachment.mediaType,
      ownerType: OWNER_TYPE,
      scopeId,
      sourceOwnerType: SOURCE_OWNER_TYPE,
      sourceKind: this.sourceKind,
      sourceName: this.sourceName,
      url: attachment.webUrl,
      baseUrl: this.config.confluence.baseUrl,
      byteSize: attachment.fileSize,
      metadata: {
        spaceKey: attachment.spaceKey,
        spaceName: attachment.spaceName,
      },
      storeInternally: this.config.ingestion.storeInternally,
    };
  }

  private buildFinalizationRequest(
    registration: ContentRegistrationRequest,
    readUrl: string,
  ): IngestionFinalizationRequest {
    return { ...registration, fileUrl: readUrl };
  }

  /**
   * When running in cluster_local auth mode, rewrite the writeUrl to route through the ingestion
   * service's scoped upload endpoint. This avoids requiring external network access (hairpinning
   * through the gateway).
   */
  private correctWriteUrl(writeUrl: string): string {
    if (this.config.unique.serviceAuthMode !== 'cluster_local') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');
    return `${this.config.unique.ingestionServiceBaseUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
  }

  private async uploadBuffer(writeUrl: string, buffer: Buffer, contentType: string): Promise<void> {
    const { statusCode } = await request(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(buffer.byteLength),
        'x-ms-blob-type': 'BlockBlob',
      },
      body: buffer,
      dispatcher: this.dispatcher,
    });

    assert.ok(statusCode >= 200 && statusCode < 300, `Upload failed with status ${statusCode}`);
  }

  private async uploadStream(
    writeUrl: string,
    stream: Readable,
    contentType: string,
    contentLength: number,
  ): Promise<void> {
    const { statusCode } = await request(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        'Content-Length': String(contentLength),
        'x-ms-blob-type': 'BlockBlob',
      },
      body: stream,
      dispatcher: this.dispatcher,
    });

    assert.ok(statusCode >= 200 && statusCode < 300, `Upload failed with status ${statusCode}`);
  }
}
