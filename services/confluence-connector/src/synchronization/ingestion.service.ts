import assert from 'node:assert';
import { Readable } from 'node:stream';
import type pino from 'pino';
import { request } from 'undici';
import type { ConfluenceConfig } from '../config';
import type { IngestionConfig } from '../config/ingestion.schema';
import { getSourceKind } from '../constants/ingestion.constants';
import type { ServiceRegistry } from '../tenant';
import type {
  ContentRegistrationRequest,
  IngestionApiResponse,
  IngestionFinalizationRequest,
} from '../unique-api/types/ingestion.types';
import { UniqueApiClient } from '../unique-api/types/unique-api-client.types';
import { sanitizeError } from '../utils/normalize-error';
import type { FetchedPage } from './sync.types';

const OWNER_TYPE = 'SCOPE';
const SOURCE_OWNER_TYPE = 'COMPANY';

const MIME_TYPES: Record<string, string> = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  ppt: 'application/vnd.ms-powerpoint',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  txt: 'text/plain',
  csv: 'text/csv',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  svg: 'image/svg+xml',
  zip: 'application/zip',
  xml: 'application/xml',
  json: 'application/json',
  html: 'text/html',
  htm: 'text/html',
};

const DEFAULT_MIME_TYPE = 'application/octet-stream';

export class IngestionService {
  private readonly uniqueApiClient: UniqueApiClient;
  private readonly logger: pino.Logger;
  private readonly sourceKind: string;
  private readonly sourceName: string;

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly ingestionConfig: IngestionConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    this.uniqueApiClient = serviceRegistry.getService(UniqueApiClient);
    this.logger = serviceRegistry.getServiceLogger(IngestionService);
    this.sourceKind = getSourceKind(this.confluenceConfig.instanceType);
    this.sourceName = this.confluenceConfig.baseUrl;
  }

  public async ingestPage(page: FetchedPage): Promise<void> {
    if (!page.body) {
      this.logger.info({ pageId: page.id, title: page.title }, 'Skipping page with empty body');
      return;
    }

    try {
      const htmlBuffer = Buffer.from(page.body, 'utf-8');
      const key = `${this.confluenceConfig.baseUrl}/${page.id}`;

      const registrationRequest = this.buildPageRegistrationRequest(
        page,
        key,
        htmlBuffer.byteLength,
      );
      const registrationResponse =
        await this.uniqueApiClient.ingestion.registerContent(registrationRequest);

      await this.uploadBuffer(registrationResponse.writeUrl, htmlBuffer, 'text/html');

      const finalizationRequest = this.buildFinalizationRequest(
        registrationRequest,
        registrationResponse,
      );
      await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);

      this.logger.info({ pageId: page.id, title: page.title }, 'Page ingested');
    } catch (error) {
      this.logger.error(
        { pageId: page.id, title: page.title, error: sanitizeError(error) },
        'Failed to ingest page, skipping',
      );
    }
  }

  public async ingestFiles(page: FetchedPage, fileUrls: string[]): Promise<void> {
    for (const fileUrl of fileUrls) {
      try {
        const filename = this.extractFilename(fileUrl);
        const mimeType = this.getMimeType(filename);
        const key = `${this.confluenceConfig.baseUrl}/${page.id}_${filename}`;

        const fileSize = await this.getRemoteFileSize(fileUrl);

        const registrationRequest = this.buildFileRegistrationRequest(
          page,
          key,
          filename,
          mimeType,
          fileSize,
        );
        const registrationResponse =
          await this.uniqueApiClient.ingestion.registerContent(registrationRequest);

        await this.streamToWriteUrl(fileUrl, registrationResponse.writeUrl, mimeType);

        const finalizationRequest = this.buildFinalizationRequest(
          registrationRequest,
          registrationResponse,
        );
        await this.uniqueApiClient.ingestion.finalizeIngestion(finalizationRequest);

        this.logger.info({ pageId: page.id, filename, fileUrl }, 'File ingested');
      } catch (error) {
        this.logger.error(
          { pageId: page.id, fileUrl, error: sanitizeError(error) },
          'Failed to ingest file, skipping',
        );
      }
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
      this.logger.error(
        { contentKeys, error: sanitizeError(error) },
        'Failed to delete content, skipping',
      );
    }
  }

  private buildPageRegistrationRequest(
    page: FetchedPage,
    key: string,
    byteSize: number,
  ): ContentRegistrationRequest {
    return {
      key,
      title: page.title,
      mimeType: 'text/html',
      ownerType: OWNER_TYPE,
      scopeId: this.ingestionConfig.scopeId,
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

  private buildFileRegistrationRequest(
    page: FetchedPage,
    key: string,
    filename: string,
    mimeType: string,
    byteSize: number,
  ): ContentRegistrationRequest {
    return {
      key,
      title: filename,
      mimeType,
      ownerType: OWNER_TYPE,
      scopeId: this.ingestionConfig.scopeId,
      sourceOwnerType: SOURCE_OWNER_TYPE,
      sourceKind: this.sourceKind,
      sourceName: this.sourceName,
      url: page.webUrl,
      baseUrl: this.confluenceConfig.baseUrl,
      byteSize,
      metadata: {
        spaceKey: page.spaceKey,
        spaceName: page.spaceName,
      },
      storeInternally: true,
    };
  }

  private buildFinalizationRequest(
    registration: ContentRegistrationRequest,
    response: IngestionApiResponse,
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
      fileUrl: response.readUrl,
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

  private async streamToWriteUrl(
    sourceUrl: string,
    writeUrl: string,
    contentType: string,
  ): Promise<void> {
    const sourceResponse = await request(sourceUrl, { method: 'GET' });

    assert.ok(
      sourceResponse.statusCode >= 200 && sourceResponse.statusCode < 300,
      `Failed to fetch source file: status ${sourceResponse.statusCode}`,
    );

    const contentLength = sourceResponse.headers['content-length'];

    const { statusCode } = await request(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': contentType,
        'x-ms-blob-type': 'BlockBlob',
        ...(contentLength ? { 'Content-Length': String(contentLength) } : {}),
      },
      body: Readable.from(sourceResponse.body),
    });

    assert.ok(statusCode >= 200 && statusCode < 300, `Upload failed with status ${statusCode}`);
  }

  private async getRemoteFileSize(fileUrl: string): Promise<number> {
    try {
      const { statusCode, headers } = await request(fileUrl, { method: 'HEAD' });

      if (statusCode >= 200 && statusCode < 300 && headers['content-length']) {
        return Number(headers['content-length']);
      }
    } catch {
      this.logger.debug({ fileUrl }, 'HEAD request failed, byte size will be estimated from GET');
    }

    return 0;
  }

  private getMimeType(filename: string): string {
    const extension = filename.split('.').pop()?.toLowerCase();
    if (!extension) {
      return DEFAULT_MIME_TYPE;
    }
    return MIME_TYPES[extension] ?? DEFAULT_MIME_TYPE;
  }

  private extractFilename(url: string): string {
    try {
      const pathname = new URL(url).pathname;
      return pathname.split('/').pop() ?? url;
    } catch {
      return url.split('/').pop() ?? url;
    }
  }
}
