import { Client } from '@microsoft/microsoft-graph-client';
import type { Drive, DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DEFAULT_MAX_FILE_SIZE_BYTES } from '../constants/defaults.constants';
import { ModerationStatus } from './sharepoint.types';
import { GraphClientFactory } from './graph-client.factory';

@Injectable()
export class GraphApiService {
    private readonly logger = new Logger(this.constructor.name);
    private readonly graphClient: Client;

    // 🔧 TEST LIMIT - Remove after testing
    private readonly TEST_SCAN_LIMIT = 10;

    public constructor(
        private readonly graphClientFactory: GraphClientFactory,
        private readonly configService: ConfigService,
    ) {
        this.graphClient = this.graphClientFactory.createClient();
    }

    public async findAllSyncableFilesForSite(siteId: string): Promise<DriveItem[]> {
        this.logger.log(`Starting recursive file scan for site: ${siteId}`);

        const drives = await this.getDrivesForSite(siteId);
        const allSyncableFiles: DriveItem[] = [];

        for (const drive of drives) {
            if (!drive.id) {
                this.logger.warn(`Drive ${drive.name} has no ID, skipping`);
                continue;
            }

            this.logger.debug(`Scanning library (drive): ${drive.name} (${drive.id})`);
            const filesInDrive = await this.recursivelyFetchSyncableFiles(drive.id, 'root');
            allSyncableFiles.push(...filesInDrive);

            // 🔧 TEST LIMIT - Final limit in case we got slightly over
            if (allSyncableFiles.length > this.TEST_SCAN_LIMIT) {
                this.logger.log(`🔧 TEST MODE: Limiting scan to ${this.TEST_SCAN_LIMIT} files`);
                return allSyncableFiles.slice(0, this.TEST_SCAN_LIMIT);
            }
        }

        this.logger.log(
            `Completed scan for site ${siteId}. Found ${allSyncableFiles.length} syncable files.`,
        );
        return allSyncableFiles;
    }

    private async getDrivesForSite(siteId: string): Promise<Drive[]> {
        try {
            this.logger.debug(`Fetching drives for site: ${siteId}`);

            // Use Graph SDK's fluent API with automatic pagination handling
            const drives = await this.graphClient.api(`/sites/${siteId}/drives`).get();

            const allDrives = drives?.value || [];
            this.logger.log(`Found ${allDrives.length} drives for site ${siteId}`);
            return allDrives;
        } catch (error) {
            this.logger.error(`Failed to fetch drives for site ${siteId}:`, error);
            throw error;
        }
    }

    private async recursivelyFetchSyncableFiles(
        driveId: string,
        itemId: string,
    ): Promise<DriveItem[]> {
        const syncableFiles: DriveItem[] = [];
        const selectFields = [
            'id',
            'name',
            'webUrl',
            'size',
            'lastModifiedDateTime',
            'folder',
            'file',
            'listItem',
            'parentReference',
        ];
        const expandFields = 'listItem($expand=fields)';

        try {
            this.logger.debug(`Fetching items for drive ${driveId}, item ${itemId}`);

            let url = `/drives/${driveId}/items/${itemId}/children`;

            // Handle pagination - Graph SDK .get() only returns first page
            while (url) {
                const response = await this.graphClient
                    .api(url)
                    .select(selectFields)
                    .expand(expandFields)
                    .get();

                const items: DriveItem[] = response?.value || [];

                for (const driveItem of items) {
                    // Ensure parentReference has driveId
                    // TODO remove this reassigning of driveId after test running it
                    if (driveItem.parentReference) {
                        driveItem.parentReference.driveId = driveId;
                    }
                    if (!driveItem.parentReference && driveItem.listItem?.parentReference) {
                        driveItem.parentReference = driveItem.listItem.parentReference;
                    }

                    if (driveItem.folder && driveItem.id) {
                        // Recursively fetch files from subfolders
                        if (syncableFiles.length > 0) return syncableFiles; // TODO REMOVE THIS TEST LINE
                        const filesInSubfolder = await this.recursivelyFetchSyncableFiles(
                            driveId,
                            driveItem.id,
                        );
                        syncableFiles.push(...filesInSubfolder);
                    } else if (driveItem.file) {
                        if (this.isFileSyncable(driveItem)) {
                            syncableFiles.push(driveItem);
                        }
                    }
                }
                // Handle pagination - check for @odata.nextLink
                url = response['@odata.nextLink']
                    ? response['@odata.nextLink']
                    : '';
            }

            this.logger.log(
                `Found ${syncableFiles.length} syncable files in drive ${driveId}, item ${itemId}`,
            );
            return syncableFiles;
        } catch (error) {
            this.logger.error(`Failed to fetch items for drive ${driveId}, item ${itemId}:`, error);
            throw error;
        }
    }

    private isFileSyncable(item: DriveItem): boolean {
        const syncColumnName = this.configService.get<string>('sharepoint.syncColumnName') ?? '';
        const allowedMimeTypes = this.configService.get<string[]>('sharepoint.allowedMimeTypes') ?? [];
        const fields = item.listItem?.fields as Record<string, unknown> | undefined;

        if (!fields) {
            this.logger.debug(`File ${item.name} has no listItem fields, skipping`);
            return false;
        }

        const hasSyncFlag = (fields as Record<string, unknown>)[syncColumnName] === true;
        const moderation = (fields as Record<string, unknown>).OData__ModerationStatus as
            | ModerationStatus
            | undefined;
        const isApproved = moderation === ModerationStatus.Approved;
        const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);

        // hasSyncFlag && && isApproved
        const syncable = Boolean(isAllowedMimeType);

        if (!syncable) {
            this.logger.debug(
                `File ${item.name} not syncable - syncFlag: ${hasSyncFlag}, approved: ${isApproved}, allowedMimeType: ${isAllowedMimeType}`,
            );
        }

        return syncable;
    }

    public async downloadFileContent(driveId: string, itemId: string): Promise<Buffer> {
        this.logger.log(`Downloading file content for item ${itemId} from drive ${driveId}`);
        const maxFileSizeBytes =
            this.configService.get<number>('pipeline.maxFileSizeBytes') ?? DEFAULT_MAX_FILE_SIZE_BYTES;

        try {
            const stream: ReadableStream = await this.graphClient
                .api(`/drives/${driveId}/items/${itemId}/content`)
                .getStream();

            const chunks: Buffer[] = [];
            let totalSize = 0;
            let lastLog = 0;

            for await (const chunk of stream) {
                const bufferChunk = Buffer.from(chunk);
                totalSize += bufferChunk.length;

                if (totalSize > maxFileSizeBytes) {
                    // Cancel the stream by getting a reader and cancelling it
                    const reader = stream.getReader();
                    await reader.cancel();
                    reader.releaseLock();
                    throw new Error(`File size exceeds maximum limit of ${maxFileSizeBytes} bytes.`);
                }

                chunks.push(bufferChunk);

                if (totalSize - lastLog > 1_000_000) {
                    lastLog = totalSize;
                    this.logger.log(`Downloaded ${Math.round(totalSize / 1024 / 1024)} MB so far...`);
                }
            }

            this.logger.log(`File download completed. Total size: ${totalSize} bytes.`);
            return Buffer.concat(chunks);
        } catch (error) {
            this.logger.error(`Failed to download file content for item ${itemId}:`, error);
            throw error;
        }
    }
}
