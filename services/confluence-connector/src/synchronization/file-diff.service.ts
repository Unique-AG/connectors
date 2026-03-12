import assert from 'node:assert';
import type { FileDiffItem, FileDiffResponse, UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import { groupBy } from 'remeda';
import type { ConfluenceConfig } from '../config';
import { getSourceKind } from '../constants/ingestion.constants';
import type { DiscoveredAttachment, DiscoveredPage, FileDiffResult } from './sync.types';

export class FileDiffService {
  private readonly logger = new Logger(FileDiffService.name);

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly tenantName: string,
    private readonly useV1KeyFormat: boolean,
    private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  public async computeDiff(
    discoveredPages: DiscoveredPage[],
    discoveredAttachments: DiscoveredAttachment[] = [],
  ): Promise<FileDiffResult> {
    this.logger.log({
      pageCount: discoveredPages.length,
      attachmentCount: discoveredAttachments.length,
      msg: 'Performing file diff',
    });

    const pagesBySpace = groupBy(discoveredPages, (page) => page.spaceKey);
    const attachmentsBySpace = groupBy(discoveredAttachments, (attachment) => attachment.spaceKey);
    const allSpaceKeys = new Set([
      ...Object.keys(pagesBySpace),
      ...Object.keys(attachmentsBySpace),
    ]);
    const sourceKind = getSourceKind(this.confluenceConfig.instanceType);

    const result: FileDiffResult = {
      newItemIds: [],
      updatedItemIds: [],
      deletedItemIds: [],
      movedItemIds: [],
    };

    for (const spaceKey of allSpaceKeys) {
      const pages = pagesBySpace[spaceKey] ?? [];
      const attachments = attachmentsBySpace[spaceKey] ?? [];

      const pageItems = this.buildPageDiffItems(pages);
      const attachmentItems = this.buildAttachmentDiffItems(attachments);
      const fileDiffItems = [...pageItems, ...attachmentItems];

      const firstItem = pages[0] ?? attachments[0];
      assert.ok(firstItem, `Expected at least one page or attachment for space "${spaceKey}"`);

      const basePartialKey = `${firstItem.spaceId}_${spaceKey}`;
      const partialKey = this.useV1KeyFormat
        ? basePartialKey
        : `${this.tenantName}/${basePartialKey}`;

      const diffResponse = await this.uniqueApiClient.ingestion.performFileDiff(
        fileDiffItems,
        partialKey,
        sourceKind,
        this.confluenceConfig.baseUrl,
      );

      this.validateNoAccidentalFullDeletion(fileDiffItems, diffResponse);

      result.newItemIds.push(...diffResponse.newFiles);
      result.updatedItemIds.push(...diffResponse.updatedFiles);
      result.deletedItemIds.push(...diffResponse.deletedFiles);
      result.movedItemIds.push(...diffResponse.movedFiles);
    }

    this.logger.log({
      newItems: result.newItemIds.length,
      updatedItems: result.updatedItemIds.length,
      deletedItems: result.deletedItemIds.length,
      movedItems: result.movedItemIds.length,
      msg: 'File diff completed',
    });

    return result;
  }

  private buildPageDiffItems(pages: DiscoveredPage[]): FileDiffItem[] {
    return pages.map((page) => ({
      key: page.id,
      url: page.webUrl,
      updatedAt: page.versionTimestamp,
    }));
  }

  private buildAttachmentDiffItems(attachments: DiscoveredAttachment[]): FileDiffItem[] {
    return attachments.map((attachment) => ({
      key: attachment.id,
      url: attachment.webUrl,
      updatedAt: attachment.versionTimestamp ?? '',
    }));
  }

  private validateNoAccidentalFullDeletion(
    submittedItems: FileDiffItem[],
    diffResponse: FileDiffResponse,
  ): void {
    if (diffResponse.deletedFiles.length === 0) {
      return;
    }

    const hasNewOrUpdated =
      diffResponse.newFiles.length > 0 || diffResponse.updatedFiles.length > 0;

    if (submittedItems.length === 0 && diffResponse.deletedFiles.length > 0) {
      this.logger.error({
        submittedCount: 0,
        deletedCount: diffResponse.deletedFiles.length,
        msg: 'File diff would delete all files because zero items were submitted. Aborting to prevent accidental full deletion.',
      });
      assert.fail(
        `Submitted 0 items to file diff but ${diffResponse.deletedFiles.length} files would be deleted. Aborting sync.`,
      );
    }

    if (!hasNewOrUpdated && diffResponse.deletedFiles.length >= submittedItems.length) {
      this.logger.error({
        submittedCount: submittedItems.length,
        deletedCount: diffResponse.deletedFiles.length,
        msg: 'File diff would delete all files with zero new or updated items. Aborting to prevent accidental full deletion.',
      });
      assert.fail(
        `File diff would delete ${diffResponse.deletedFiles.length} files with zero new or updated items. Aborting sync.`,
      );
    }
  }
}
