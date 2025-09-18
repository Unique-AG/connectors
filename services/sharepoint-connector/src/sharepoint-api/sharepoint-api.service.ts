import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Client } from 'undici';
import { SharepointAuthService } from '../auth/sharepoint-auth.service';
import { DEFAULT_MAX_FILE_SIZE_BYTES } from '../constants/defaults.constants';
import { SHAREPOINT_HTTP_CLIENT } from '../http-client.tokens';
import {
  type Drive,
  type DriveItem,
  ModerationStatus,
  type SharePointApiResponseData,
} from '../types/sharepoint.types';

@Injectable()
export class SharepointApiService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly GRAPH_API_BASE_URL: string;

  public constructor(
    @Inject(SHAREPOINT_HTTP_CLIENT) private readonly httpClient: Client,
    private readonly sharepointAuthService: SharepointAuthService,
    private readonly configService: ConfigService,
  ) {
    this.GRAPH_API_BASE_URL = `${this.configService.get<string>(
      'sharepoint.apiUrl',
      'https://graph.microsoft.com',
    )}/v1.0`;
  }

  public async findAllSyncableFilesForSite(siteId: string): Promise<DriveItem[]> {
    this.logger.debug(`Starting recursive file scan for site: ${siteId}`);
    const drives = await this.getDrivesForSite(siteId);
    const allSyncableFiles: DriveItem[] = [];

    for (const drive of drives) {
      this.logger.debug(`Scanning library (drive): ${drive.name} (${drive.id})`);
      const filesInDrive = await this.recursivelyFetchSyncableFiles(drive.id, 'root');
      allSyncableFiles.push(...filesInDrive);
    }

    this.logger.debug(
      `Completed scan for site ${siteId}. Found ${allSyncableFiles.length} syncable files.`,
    );
    return allSyncableFiles;
  }

  private async getDrivesForSite(siteId: string): Promise<Drive[]> {
    const allDrives: Drive[] = [];
    let url = `${this.GRAPH_API_BASE_URL}/sites/${siteId}/drives`;

    while (url) {
      const token = await this.sharepointAuthService.getToken();
      const urlObj = new URL(url);
      const path = urlObj.pathname + urlObj.search;

      try {

      const { body } = await this.httpClient.request({
        method: 'GET',
        path,
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        throwOnError: true,
      });

      const responseData = (await body.json()) as SharePointApiResponseData<Drive>;
      allDrives.push(...(responseData.value || []));
      url = responseData['@odata.nextLink'] || '';
      } catch(error) {
          this.logger.error(`Failed to fetch drive for site ${siteId}. ${error}`);
      }
    }
    return allDrives;
  }

  private async recursivelyFetchSyncableFiles(
    driveId: string,
    itemId: string,
  ): Promise<DriveItem[]> {
    const syncableFiles: DriveItem[] = [];
    const queryParams =
      'select=id,name,webUrl,size,lastModifiedDateTime,folder,file,listItem,parentReference&expand=listItem(expand=fields,parentReference)';
    let url = `${this.GRAPH_API_BASE_URL}/drives/${driveId}/items/${itemId}/children?${queryParams}`;

    while (url) {
      const token = await this.sharepointAuthService.getToken();
      const urlObj = new URL(url);
      const path = urlObj.pathname + urlObj.search;

      const { body } = await this.httpClient.request({
        method: 'GET',
        path,
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        throwOnError: true,
      });

      const responseData = (await body.json()) as SharePointApiResponseData<DriveItem>;
      const items: DriveItem[] = responseData.value || [];

      for (const item of items) {
        if (item.parentReference) {
          item.parentReference.driveId = driveId;
        }
        if (!item.parentReference && item.listItem?.parentReference) {
          item.parentReference = item.listItem.parentReference;
        }
        if (item.folder) {
          const filesInSubfolder = await this.recursivelyFetchSyncableFiles(driveId, item.id);
          syncableFiles.push(...filesInSubfolder);
        } else if (item.file) {
          if (this.isFileSyncable(item)) {
            syncableFiles.push(item);
          }
        }
      }
      url = responseData['@odata.nextLink'] || '';
    }
    return syncableFiles;
  }

  private isFileSyncable(item: DriveItem): boolean {
    const syncColumnName = this.configService.get<string>('sharepoint.syncColumnName') ?? '';
    const allowedMimeTypes = this.configService.get<string[]>('sharepoint.allowedMimeTypes') ?? [];
    const fields = item.listItem?.fields as Record<string, unknown> | undefined;
    if (!fields) return false;
    const hasSyncFlag = (fields as Record<string, unknown>)[syncColumnName] === true;
    const moderation = (fields as Record<string, unknown>).OData__ModerationStatus as
      | ModerationStatus
      | undefined;
    const isApproved = moderation === ModerationStatus.Approved;
    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);
    return Boolean(hasSyncFlag && isApproved && isAllowedMimeType);
  }

  public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
    this.logger.debug(`Downloading file content for item ${itemId} from drive ${driveId}`);
    const maxFileSizeBytes =
      this.configService.get<number>('pipeline.maxFileSizeBytes') ?? DEFAULT_MAX_FILE_SIZE_BYTES;

    const token = await this.sharepointAuthService.getToken();
    const downloadUrl = `${this.GRAPH_API_BASE_URL}/drives/${driveId}/items/${itemId}/content`;
    const urlObj = new URL(downloadUrl);
    const path = urlObj.pathname + urlObj.search;

    const { body: responseStream } = await this.httpClient.request({
      method: 'GET',
      path,
      headers: { Authorization: `Bearer ${token}` },
      throwOnError: true,
    });

    return await new Promise<Buffer>((resolve, reject) => {
      const chunks: Buffer[] = [];
      let totalSize = 0;
      responseStream.on('data', (chunk: Buffer) => {
        totalSize += chunk.length;
        if (totalSize > maxFileSizeBytes) {
          responseStream.destroy();
          reject(new Error(`File size exceeds maximum limit of ${maxFileSizeBytes} bytes.`));
        }
        chunks.push(chunk);
      });
      responseStream.on('end', () => {
        this.logger.log(`File download completed. Size: ${totalSize} bytes.`);
        resolve(Buffer.concat(chunks));
      });
      responseStream.on('error', (error) => {
        this.logger.error(`File download stream failed: ${error.message}`);
        reject(error);
      });
    });
  }
}
