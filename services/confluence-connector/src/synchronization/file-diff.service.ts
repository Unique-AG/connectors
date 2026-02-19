import assert from 'node:assert';
import type pino from 'pino';
import type { ConfluenceConfig } from '../config';
import type { IngestionConfig } from '../config/ingestion.schema';
import { getSourceKind, IngestFiles } from '../constants/ingestion.constants';
import type { ServiceRegistry } from '../tenant';
import type { FileDiffItem, FileDiffResponse } from '../unique-api/types/ingestion.types';
import { UniqueApiClient } from '../unique-api/types/unique-api-client.types';
import { parseHrefs, stripQueryAndFragment } from '../utils/html-link-parser';
import type { DiscoveredPage, FileDiffResult } from './sync.types';

export class FileDiffService {
  private readonly uniqueApiClient: UniqueApiClient;
  private readonly logger: pino.Logger;

  public constructor(
    private readonly confluenceConfig: ConfluenceConfig,
    private readonly ingestionConfig: IngestionConfig,
    serviceRegistry: ServiceRegistry,
  ) {
    this.uniqueApiClient = serviceRegistry.getService(UniqueApiClient);
    this.logger = serviceRegistry.getServiceLogger(FileDiffService);
  }

  public async computeDiff(
    discoveredPages: DiscoveredPage[],
    pageBodies?: ReadonlyMap<string, string>,
  ): Promise<FileDiffResult> {
    const fileDiffItems = this.buildFileDiffItems(discoveredPages, pageBodies);

    this.logger.info({ itemCount: fileDiffItems.length }, 'Performing file diff');

    const diffResponse = await this.uniqueApiClient.ingestion.performFileDiff(
      fileDiffItems,
      this.confluenceConfig.baseUrl,
      getSourceKind(this.confluenceConfig.instanceType),
      this.confluenceConfig.baseUrl,
    );

    this.validateNoAccidentalFullDeletion(fileDiffItems, diffResponse);

    this.logger.info(
      {
        new: diffResponse.newFiles.length,
        updated: diffResponse.updatedFiles.length,
        deleted: diffResponse.deletedFiles.length,
        moved: diffResponse.movedFiles.length,
      },
      'File diff completed',
    );

    return this.categorizeByPageId(diffResponse);
  }

  private buildFileDiffItems(
    pages: DiscoveredPage[],
    pageBodies?: ReadonlyMap<string, string>,
  ): FileDiffItem[] {
    const items: FileDiffItem[] = [];

    for (const page of pages) {
      items.push({
        key: page.id,
        url: page.webUrl,
        updatedAt: page.versionTimestamp,
      });

      if (this.isFileIngestionEnabled() && pageBodies) {
        const body = pageBodies.get(page.id);
        if (body) {
          const fileItems = this.extractLinkedFileItems(page, body);
          items.push(...fileItems);
        }
      }
    }

    return items;
  }

  private extractLinkedFileItems(page: DiscoveredPage, htmlBody: string): FileDiffItem[] {
    const hrefs = parseHrefs(htmlBody);
    const allowedExtensions = this.ingestionConfig.allowedFileExtensions ?? [];

    return hrefs
      .filter((href) => {
        const cleanUrl = stripQueryAndFragment(href);
        const extension = cleanUrl.split('.').pop()?.toLowerCase();
        return extension !== undefined && allowedExtensions.includes(extension);
      })
      .map((href) => {
        const absoluteUrl = new URL(href, this.confluenceConfig.baseUrl).toString();
        const cleanUrl = stripQueryAndFragment(href);
        const filename = cleanUrl.split('/').pop() ?? href;
        return {
          key: `${page.id}_${filename}`,
          url: absoluteUrl,
          updatedAt: page.versionTimestamp,
        };
      });
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
      this.logger.error(
        { submittedCount: 0, deletedCount: diffResponse.deletedFiles.length },
        'File diff would delete all files because zero items were submitted. Aborting to prevent accidental full deletion.',
      );
      assert.fail(
        `Submitted 0 items to file diff but ${diffResponse.deletedFiles.length} files would be deleted. Aborting sync.`,
      );
    }

    if (!hasNewOrUpdated && diffResponse.deletedFiles.length >= submittedItems.length) {
      this.logger.error(
        { submittedCount: submittedItems.length, deletedCount: diffResponse.deletedFiles.length },
        'File diff would delete all files with zero new or updated items. Aborting to prevent accidental full deletion.',
      );
      assert.fail(
        `File diff would delete ${diffResponse.deletedFiles.length} files with zero new or updated items. Aborting sync.`,
      );
    }
  }

  private categorizeByPageId(diffResponse: FileDiffResponse): FileDiffResult {
    return {
      newPageIds: this.extractPageIds(diffResponse.newFiles),
      updatedPageIds: this.extractPageIds(diffResponse.updatedFiles),
      deletedPageIds: this.extractPageIds(diffResponse.deletedFiles),
      deletedKeys: [...diffResponse.deletedFiles],
      movedPageIds: this.extractPageIds(diffResponse.movedFiles),
    };
  }

  private extractPageIds(keys: string[]): string[] {
    const pageIds = new Set<string>();
    for (const key of keys) {
      const underscoreIndex = key.indexOf('_');
      pageIds.add(underscoreIndex === -1 ? key : key.substring(0, underscoreIndex));
    }
    return [...pageIds];
  }

  private isFileIngestionEnabled(): boolean {
    return this.ingestionConfig.ingestFiles === IngestFiles.Enabled;
  }
}
