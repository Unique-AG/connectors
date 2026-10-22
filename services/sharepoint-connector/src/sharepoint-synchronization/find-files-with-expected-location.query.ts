import { Injectable, Logger } from '@nestjs/common';
import { filter, isNonNullish, isNullish, map, pipe } from 'remeda';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { UniqueFile } from '../unique-api/unique-files/unique-files.types';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { buildFileDiffKey, getItemUrl } from '../utils/sharepoint.util';
import { ScopeManagementService } from './scope-management.service';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

interface Input {
  diffKeys: string[];
  items: SharepointContentItem[];
  scopes: ScopeWithPath[] | null;
  context: SharepointSyncContext;
}

export interface FileWithExpectedLocation {
  contentId: string;
  key: string;
  diffKey: string;
  currentScopeId: string;
  expectedScopeId: string;
  expectedUrl: string;
}

@Injectable()
export class FindFilesWithExpectedLocationQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly scopeManagementService: ScopeManagementService,
  ) {}

  // Loads the files stored in Unique for the given file-diff keys and pairs each with the scope
  // and URL its current SharePoint item maps to. Files without a matching item or scope are left
  // out.
  public async execute(input: Input): Promise<FileWithExpectedLocation[]> {
    const { diffKeys, items, scopes, context } = input;
    const { siteId } = context.siteConfig;

    const files = await this.uniqueFilesService.getFilesByKeys(
      diffKeys.map((key) => `${siteId.value}/${key}`),
    );
    const itemsByKey = new Map(items.map((item) => [buildFileDiffKey(item), item]));

    return pipe(
      files,
      map((file) => this.withExpectedLocation(file, itemsByKey, scopes, context)),
      filter(isNonNullish),
    );
  }

  private withExpectedLocation(
    file: UniqueFile,
    itemsByKey: ReadonlyMap<string, SharepointContentItem>,
    scopes: ScopeWithPath[] | null,
    context: SharepointSyncContext,
  ): FileWithExpectedLocation | null {
    const { siteId } = context.siteConfig;
    const logPrefix = `[Site: ${siteId}]`;
    const diffKey = file.key.replace(`${siteId.value}/`, '');

    const item = itemsByKey.get(diffKey);
    if (isNullish(item)) {
      this.logger.warn(
        `${logPrefix} Could not find SharePoint item for file with key: ${file.key}`,
      );
      return null;
    }

    const expectedScopeId = this.scopeManagementService.determineScopeForItem(
      item,
      scopes,
      context,
    );
    if (isNullish(expectedScopeId)) {
      this.logger.warn(`${logPrefix} Could not determine scope for file with key: ${file.key}`);
      return null;
    }

    return {
      contentId: file.id,
      key: file.key,
      diffKey,
      currentScopeId: file.ownerId,
      expectedScopeId,
      expectedUrl: getItemUrl(item),
    };
  }
}
