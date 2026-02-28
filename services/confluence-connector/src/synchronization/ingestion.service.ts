import assert from 'node:assert';
import type pino from 'pino';
import { request } from 'undici';
import type { ConfluenceConfig } from '../config';
import {
  getSourceKind,
  OWNER_TYPE,
  SOURCE_OWNER_TYPE,
} from '../constants/ingestion.constants';
import type {
  ContentRegistrationRequest,
  IngestionFinalizationRequest,
} from '../unique-api/types';
import type { UniqueApiClient } from '../unique-api';
import type { FetchedPage } from './sync.types';

export class IngestionService {
  private readonly sourceKind: string;
  private readonly sourceName: string;

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly tenantName: string,
    private readonly uniqueApiClient: UniqueApiClient,
    private readonly logger: pino.Logger,
  ) {
    this.sourceKind = getSourceKind(this.confluenceConfig.instanceType);
    this.sourceName = this.confluenceConfig.baseUrl;
  }

  public async ingestPage(page: FetchedPage, scopeId: string): Promise<void> {
    if (!page.body) {
      this.logger.info({ pageId: page.id, title: page.title }, 'Skipping page with empty body');
      return;
    }

    try {
      const htmlBuffer = Buffer.from(page.body, 'utf-8');
      const key = `${this.tenantName}/${page.spaceKey}/${page.id}`;

      const registrationRequest = this.buildPageRegistrationRequest(
        page,
        key,
        htmlBuffer.byteLength,
        scopeId,
      );
      const registrationResponse =
        await this.uniqueApiClient.ingestion.registerContent(registrationRequest);

      await this.uploadBuffer(registrationResponse.writeUrl, htmlBuffer, 'text/html');

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse.readUrl,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);

      this.logger.info({ pageId: page.id, title: page.title }, 'Page ingested');
    } catch (error) {
      this.logger.error({
        pageId: page.id,
        title: page.title,
        err: error,
        msg: 'Failed to ingest page, skipping',
      });
    }
  }

  public async deleteContent(contentKeys: string[]): Promise<void> {
    if (contentKeys.length === 0) return;

    try {
      const files = await this.uniqueApiClient.files.getByKeys(contentKeys);
      if (files.length === 0) {
        this.logger.info(
          { keyCount: contentKeys.length },
          'No content found for keys, nothing to delete',
        );
        return;
      }

      const contentIds = files.map((f) => f.id);
      const deletedCount = await this.uniqueApiClient.files.deleteByIds(contentIds);
      this.logger.info(
        { requestedCount: contentKeys.length, resolvedCount: files.length, deletedCount },
        'Content deleted',
      );
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
      mimeType: 'text/html',
      ownerType: OWNER_TYPE,
      scopeId,
      sourceOwnerType: SOURCE_OWNER_TYPE,
      sourceKind: this.sourceKind,
      sourceName: this.sourceName,
      url: page.webUrl,
      baseUrl: this.confluenceConfig.baseUrl,
      byteSize,
      metadata: {
        confluenceLabels: page.metadata?.confluenceLabels ?? [],
        spaceKey: page.spaceKey,
        spaceName: page.spaceName,
      },
      storeInternally: true,
    };
  }

  private buildFinalizationRequest(
    registration: ContentRegistrationRequest,
    readUrl: string,
  ): IngestionFinalizationRequest {
    return {
      key: registration.key,
      title: registration.title,
      mimeType: registration.mimeType,
      ownerType: registration.ownerType,
      byteSize: registration.byteSize,
      scopeId: registration.scopeId,
      sourceOwnerType: registration.sourceOwnerType,
      sourceName: registration.sourceName,
      sourceKind: registration.sourceKind,
      fileUrl: readUrl,
      url: registration.url,
      baseUrl: registration.baseUrl,
      metadata: registration.metadata,
      storeInternally: registration.storeInternally,
    };
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

}
