import { Injectable, Logger } from '@nestjs/common';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { Smeared } from '../utils/smeared';
import {
  type ListItemAttachmentsScanOptions,
  ScanListItemAttachmentsQuery,
} from './scan-list-item-attachments.query';

interface FetchSiteItemsOptions extends ListItemAttachmentsScanOptions {
  scanListAttachments: boolean;
}

@Injectable()
export class FetchSiteItemsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly scanListItemAttachmentsQuery: ScanListItemAttachmentsQuery,
  ) {}

  public async execute(
    siteId: Smeared,
    syncColumnName: string,
    { scanListAttachments, ...attachmentScanOptions }: FetchSiteItemsOptions,
  ): Promise<{ items: SharepointContentItem[]; directories: SharepointDirectoryItem[] }> {
    const logPrefix = `[Site: ${siteId}]`;
    const lists = await this.graphApiService.getSiteLists(siteId);

    // Every scan must succeed — partial results would cause the diff to treat missing items as
    // deletions and result in unnecessary re-ingestions. We have retries in place to handle
    // transient errors so if any call for site fails, so does entire site scan.
    const [aspxPages, filesResult, listAttachments] = await Promise.all([
      this.graphApiService.getAspxPagesForSite(siteId, syncColumnName, lists),
      this.graphApiService.getAllFilesForSite(siteId, syncColumnName),
      scanListAttachments
        ? this.scanListItemAttachmentsQuery.execute(
            siteId,
            syncColumnName,
            attachmentScanOptions,
            lists,
          )
        : [],
    ]);

    const items = [...aspxPages, ...filesResult.items, ...listAttachments];

    this.logger.log(
      `${logPrefix} Completed scan. Found ${items.length} total items marked for synchronization.`,
    );
    return { items, directories: filesResult.directories };
  }
}
