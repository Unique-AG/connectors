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
    discoveredAttachments: DiscoveredAttachment[],
  ): Promise<FileDiffResult> {
    this.logger.log({
      pageCount: discoveredPages.length,
      attachmentCount: discoveredAttachments.length,
      msg: 'Performing file diff',
    });

    const pagesBySpace = groupBy(discoveredPages, (page) => page.spaceKey);
    const attachmentsBySpace = groupBy(discoveredAttachments, (attachment) => attachment.spaceKey);
    // Attachment spaces are typically a subset of page spaces, but we include both for safety.
    const allSpaceKeys = new Set([
      ...Object.keys(pagesBySpace),
      ...Object.keys(attachmentsBySpace),
    ]);
    const sourceKind = getSourceKind(this.confluenceConfig.instanceType);

    const result: FileDiffResult = {
      newItemIds: [],
      updatedItemIds: [],
      deletedItems: [],
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

      await this.validateNoAccidentalFullDeletion(fileDiffItems, diffResponse, partialKey);

      result.newItemIds.push(...diffResponse.newFiles);
      result.updatedItemIds.push(...diffResponse.updatedFiles);
      result.deletedItems.push(...diffResponse.deletedFiles.map((id) => ({ id, partialKey })));
      result.movedItemIds.push(...diffResponse.movedFiles);
    }

    this.logger.log({
      newItems: result.newItemIds.length,
      updatedItems: result.updatedItemIds.length,
      deletedItems: result.deletedItems.length,
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
      key: `${attachment.pageId}::${attachment.id}`,
      url: attachment.webUrl,
      updatedAt: attachment.versionTimestamp ?? '',
    }));
  }

  private async validateNoAccidentalFullDeletion(
    submittedItems: FileDiffItem[],
    diffResponse: FileDiffResponse,
    partialKey: string,
  ): Promise<void> {
    // If there are no files to be deleted, there's no point in checking further, we will surely not
    // perform full deletion.
    if (diffResponse.deletedFiles.length === 0) {
      return;
    }

    // If the file diff indicated we should delete all files by having submitted no files to the
    // diff, it most probably means that we have some kind of bug in fetching the pages from
    // Confluence and we should not proceed with the sync to avoid costly re-ingestions. In case
    // user actually wants to delete all files from a space, they should leave one page labeled
    // for synchronization.
    if (submittedItems.length === 0 && diffResponse.deletedFiles.length > 0) {
      this.logger.error({
        submittedCount: 0,
        deletedCount: diffResponse.deletedFiles.length,
        partialKey,
        msg: 'File diff would delete all files because zero items were submitted. Aborting to prevent accidental full deletion.',
      });
      assert.fail(
        `Submitted 0 items to file diff but ${diffResponse.deletedFiles.length} files would be deleted. Aborting sync.`,
      );
    }

    // If the file diff indicated we should delete all files even when we submitted some files to
    // the diff, it most probably means that we have some kind of bug in file diff or something
    // unexpected changed in the logic (e.g. key format change). We should not proceed with the
    // sync to avoid costly re-ingestions. If user actually wants to delete all files from a space,
    // they should leave one page labeled for synchronization.
    const totalFilesInUnique = await this.uniqueApiClient.files.getCountByKeyPrefix(partialKey);
    if (diffResponse.deletedFiles.length === totalFilesInUnique) {
      this.logger.error({
        submittedCount: submittedItems.length,
        deletedCount: diffResponse.deletedFiles.length,
        totalFilesInUnique,
        partialKey,
        msg: 'File diff would delete all files stored in Unique. Aborting to prevent accidental full deletion.',
      });
      assert.fail(
        `File diff would delete all ${diffResponse.deletedFiles.length} files stored in Unique for partialKey "${partialKey}". Aborting sync to prevent accidental full deletion.`,
      );
    }
  }
}
