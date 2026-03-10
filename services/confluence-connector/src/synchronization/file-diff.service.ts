import assert from 'node:assert';
import type { FileDiffItem, FileDiffResponse, UniqueApiClient } from '@unique-ag/unique-api';
import { Logger } from '@nestjs/common';
import { groupBy } from 'remeda';
import type { ConfluenceConfig } from '../config';
import { getSourceKind } from '../constants/ingestion.constants';
import type { DiscoveredPage, FileDiffResult } from './sync.types';

export class FileDiffService {
  private readonly logger = new Logger(FileDiffService.name);

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly tenantName: string,
    private readonly useV1KeyFormat: boolean,
    private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  public async computeDiff(discoveredPages: DiscoveredPage[]): Promise<FileDiffResult> {
    this.logger.log({ pageCount: discoveredPages.length, msg: 'Performing file diff' });

    const pagesBySpace = groupBy(discoveredPages, (page) => page.spaceKey);
    const sourceKind = getSourceKind(this.confluenceConfig.instanceType);

    const result: FileDiffResult = {
      newPageIds: [],
      updatedPageIds: [],
      deletedPageIds: [],
      movedPageIds: [],
    };

    for (const [spaceKey, pages] of Object.entries(pagesBySpace)) {
      const fileDiffItems = this.buildFileDiffItems(pages);
      const firstPage = pages[0];
      assert.ok(firstPage, `Expected at least one page for space "${spaceKey}"`);

      const basePartialKey = `${firstPage.spaceId}_${spaceKey}`;
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

      result.newPageIds.push(...diffResponse.newFiles);
      result.updatedPageIds.push(...diffResponse.updatedFiles);
      result.deletedPageIds.push(...diffResponse.deletedFiles);
      result.movedPageIds.push(...diffResponse.movedFiles);
    }

    this.logger.log({
      new: result.newPageIds.length,
      updated: result.updatedPageIds.length,
      deleted: result.deletedPageIds.length,
      moved: result.movedPageIds.length,
      msg: 'File diff completed',
    });

    return result;
  }

  private buildFileDiffItems(pages: DiscoveredPage[]): FileDiffItem[] {
    return pages.map((page) => ({
      key: page.id,
      url: page.webUrl,
      updatedAt: page.versionTimestamp,
    }));
  }

  private async validateNoAccidentalFullDeletion(
    submittedItems: FileDiffItem[],
    diffResponse: FileDiffResponse,
    partialKey: string,
  ): Promise<void> {
    if (diffResponse.deletedFiles.length === 0) {
      return;
    }

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
