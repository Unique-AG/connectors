import { Injectable, Logger } from '@nestjs/common';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueFile } from '../unique-api/unique-files/unique-files.types';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { normalizeError } from '../utils/normalize-error';
import { getItemUrl } from '../utils/sharepoint.util';
import { ScopeManagementService } from './scope-management.service';

interface FileMoveData {
  contentId: string; // ingested file id
  newOwnerId: string; // new scopeId
  newUrl: string;
}

@Injectable()
export class FileMoveProcessor {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  /**
   * Processes files that have been moved to new locations in SharePoint
   */
  public async processFileMoves(
    siteId: string,
    movedFileKeys: string[],
    sharepointItems: SharepointContentItem[],
    scopes?: Scope[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}]`;
    const movedFileCompleteKeys = this.convertToFullKeys(movedFileKeys, siteId);
    let ingestedFiles: UniqueFile[] = [];

    try {
      ingestedFiles = await this.uniqueFilesService.getFilesByKeys(movedFileCompleteKeys);
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error({
        msg: `${logPrefix} Failed to get ingested files by keys from unique: ${normalizedError.message}`,
        error,
      });
      throw error;
    }

    // Prepare move data with new scopeIds and URLs
    const moveData = this.prepareFileMoveData(ingestedFiles, sharepointItems, siteId, scopes);

    this.logger.log(`${logPrefix} Prepared ${moveData.length} file move operations`);

    // Execute move operations
    let totalMoved = 0;
    for (const data of moveData) {
      try {
        await this.uniqueFilesService.moveFile(data.contentId, data.newOwnerId, data.newUrl);
        totalMoved++;
      } catch (error) {
        const normalizedError = normalizeError(error);
        this.logger.error({
          msg: `${logPrefix} Failed to move file ${data.contentId}: ${normalizedError.message}`,
          error,
        });
      }
    }

    this.logger.log(`${logPrefix} Completed move processing: ${totalMoved} content items moved`);
  }

  private convertToFullKeys(relativeKeys: string[], siteId: string): string[] {
    return relativeKeys.map((key) => `${siteId}/${key}`);
  }

  /**
   * Prepares file move data by matching existing database content with current SharePoint items
   * and determining new scope and URL for each moved file
   */
  private prepareFileMoveData(
    ingestedFiles: Array<{ id: string; key: string; ownerId: string }>,
    sharepointItems: SharepointContentItem[],
    siteId: string,
    scopes?: Scope[],
  ): FileMoveData[] {
    const logPrefix = `[SiteId: ${siteId}]`;
    const filesToMove: FileMoveData[] = [];

    for (const ingestedFile of ingestedFiles) {
      const relativeKey = ingestedFile.key.replace(`${siteId}/`, '');

      // Find the corresponding SharePoint item
      const sharepointItem = sharepointItems.find((item) => item.item.id === relativeKey);

      if (!sharepointItem) {
        this.logger.warn(
          `${logPrefix} Could not find SharePoint item for moved file with key: ${ingestedFile.key}`,
        );
        continue;
      }

      // Get the new scopeId for the new location
      const newOwnerId = this.scopeManagementService.determineScopeForItem(sharepointItem, scopes);
      if (!newOwnerId) {
        this.logger.warn(
          `${logPrefix} Could not determine scope for moved file with key: ${ingestedFile.key}`,
        );
        continue;
      }

      const newUrl = getItemUrl(sharepointItem);

      filesToMove.push({
        contentId: ingestedFile.id,
        newOwnerId,
        newUrl,
      });
    }

    return filesToMove;
  }
}
