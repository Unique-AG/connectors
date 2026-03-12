import assert from 'node:assert';
import type { Readable } from 'node:stream';
import type {
  ContentRegistrationRequest,
  IngestionFinalizationRequest,
  UniqueApiClient,
} from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import { request } from 'undici';
import type { ConfluenceApiClient } from '../confluence-api';
import type { TenantConfig } from '../config';
import {
  getSourceKind,
  INGESTION_MIME_TYPE,
  OWNER_TYPE,
  SOURCE_OWNER_TYPE,
} from '../constants/ingestion.constants';
import type { DiscoveredAttachment, FetchedPage } from './sync.types';

export class IngestionService {
  private readonly logger = new Logger(IngestionService.name);
  private readonly sourceKind: string;
  private readonly sourceName: string;

  public constructor(
    private readonly config: TenantConfig,
    private readonly tenantName: string,
    private readonly uniqueApiClient: UniqueApiClient,
    private readonly confluenceApiClient: ConfluenceApiClient,
  ) {
    this.sourceKind = getSourceKind(this.config.confluence.instanceType);
    this.sourceName = this.config.confluence.baseUrl;
  }

  public async ingestPage(page: FetchedPage, scopeId: string): Promise<void> {
    if (!page.body) {
      this.logger.log({ pageId: page.id, title: page.title, msg: 'Skipping page with empty body' });
      return;
    }

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

      const uploadUrl = this.correctWriteUrl(registrationResponse.writeUrl);
      await this.uploadBuffer(uploadUrl, htmlBuffer, INGESTION_MIME_TYPE);

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse.readUrl,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);

      this.logger.debug({ pageId: page.id, title: page.title, msg: 'Page sent for ingestion' });
    } catch (error) {
      this.logger.error({
        pageId: page.id,
        title: page.title,
        err: error,
        msg: 'Failed to ingest page, skipping',
      });
    }
  }

  public async ingestAttachment(attachment: DiscoveredAttachment, scopeId: string): Promise<void> {
    if (attachment.fileSize === 0) {
      this.logger.log({
        attachmentId: attachment.id,
        title: attachment.title,
        msg: 'Skipping zero-byte attachment',
      });
      return;
    }

    try {
      const baseKey = `${attachment.spaceId}_${attachment.spaceKey}/${attachment.id}`;
      const key = this.config.ingestion.useV1KeyFormat ? baseKey : `${this.tenantName}/${baseKey}`;

      const registrationRequest = this.buildAttachmentRegistrationRequest(
        attachment,
        key,
        scopeId,
      );
      const registrationResponse =
        await this.uniqueApiClient.ingestion.registerContent(registrationRequest);

      const uploadUrl = this.correctWriteUrl(registrationResponse.writeUrl);
      const stream = await this.confluenceApiClient.getAttachmentDownloadStream(
        attachment.downloadPath,
      );
      await this.uploadStream(uploadUrl, stream, attachment.mediaType, attachment.fileSize);

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse.readUrl,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);

      this.logger.debug({
        attachmentId: attachment.id,
        title: attachment.title,
        msg: 'Attachment sent for ingestion',
      });
    } catch (error) {
      this.logger.error({
        attachmentId: attachment.id,
        title: attachment.title,
        err: error,
        msg: 'Failed to ingest attachment, skipping',
      });
    }
  }

  public async deleteContentByKeys(contentKeys: string[]): Promise<void> {
    if (contentKeys.length === 0) {
      return;
    }

    try {
      const files = await this.uniqueApiClient.files.getByKeys(contentKeys);
      if (files.length === 0) {
        this.logger.log({
          keyCount: contentKeys.length,
          msg: 'No content found for keys, nothing to delete',
        });
        return;
      }

      const contentIds = files.map((f) => f.id);
      const deletedCount = await this.uniqueApiClient.files.deleteByIds(contentIds);
      this.logger.log({
        requestedCount: contentKeys.length,
        resolvedCount: files.length,
        deletedCount,
        msg: 'Content deleted',
      });
    } catch (error) {
      this.logger.error({ contentKeys, err: error, msg: 'Failed to delete content, skipping' });
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
      title: page.title,
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
    });

    assert.ok(statusCode >= 200 && statusCode < 300, `Upload failed with status ${statusCode}`);
  }
}
