import { Inject, Injectable, Logger } from '@nestjs/common';
import { type Counter } from '@opentelemetry/api';
import { SPC_FILE_MOVED_TOTAL } from '../metrics';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { sanitizeError } from '../utils/normalize-error';
import {
  FileWithExpectedLocation,
  FindFilesWithExpectedLocationQuery,
} from './find-files-with-expected-location.query';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

@Injectable()
export class FileMoveProcessor {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly findFilesWithExpectedLocationQuery: FindFilesWithExpectedLocationQuery,
    @Inject(SPC_FILE_MOVED_TOTAL) private readonly spcFileMovedTotal: Counter,
  ) {}

  /**
   * Processes files that have been moved to new locations in SharePoint
   */
  public async processFileMoves(
    movedFileKeys: string[],
    sharepointItems: SharepointContentItem[],
    scopes: ScopeWithPath[] | null,
    context: SharepointSyncContext,
  ): Promise<void> {
    const { siteId } = context.siteConfig;
    const logPrefix = `[Site: ${siteId}]`;
    let files: FileWithExpectedLocation[] = [];

    try {
      files = await this.findFilesWithExpectedLocationQuery.execute({
        diffKeys: movedFileKeys,
        items: sharepointItems,
        scopes,
        context,
      });
    } catch (error) {
      this.logger.error({
        msg: `${logPrefix} Failed to get ingested files by keys from unique`,
        error: sanitizeError(error),
      });
      throw error;
    }

    this.logger.log(`${logPrefix} Prepared ${files.length} file move operations`);

    let totalMoved = 0;
    for (const file of files) {
      try {
        await this.uniqueFilesService.moveFile(
          file.contentId,
          file.expectedScopeId,
          file.expectedUrl,
        );
        totalMoved++;

        this.spcFileMovedTotal.add(1, {
          sp_site_id: siteId.toString(),
          result: 'success',
        });
      } catch (error) {
        this.spcFileMovedTotal.add(1, {
          sp_site_id: siteId.toString(),
          result: 'failure',
        });

        this.logger.error({
          msg: `${logPrefix} Failed to move file ${file.contentId}`,
          contentId: file.contentId,
          error: sanitizeError(error),
        });
      }
    }

    this.logger.log(`${logPrefix} Completed move processing: ${totalMoved} content items moved`);
  }
}
