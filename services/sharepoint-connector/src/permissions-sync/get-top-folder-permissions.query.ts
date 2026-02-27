import { Injectable, Logger } from '@nestjs/common';
import { filter, isNullish, map, pipe, prop, uniqueBy } from 'remeda';
import {
  AnySharepointItem,
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { normalizeSlashes } from '../utils/paths.util';
import {
  buildIngestionItemKey,
  getUniqueParentPathFromItem,
  getUniquePathFromItem,
} from '../utils/sharepoint.util';
import { createSmeared, Smeared } from '../utils/smeared';
import { GroupMembership, Membership } from './types';
import { groupDistinctId, isTopFolder } from './utils';

interface Input {
  items: SharepointContentItem[];
  directories: SharepointDirectoryItem[];
  permissionsMap: Record<string, Membership[]>;
  rootPath: Smeared;
  siteName: Smeared;
}

@Injectable()
export class GetTopFolderPermissionsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public run(input: Input): Map<string, GroupMembership[]> {
    const { items, directories, permissionsMap, rootPath, siteName } = input;
    const allItems: AnySharepointItem[] = [...items, ...directories];

    const topFolders = this.identifyTopFolders(allItems, rootPath, siteName);
    const result = new Map<string, GroupMembership[]>();

    for (const topFolderPath of topFolders) {
      const aggregatedGroups = this.aggregateGroupPermissions(
        topFolderPath,
        allItems,
        permissionsMap,
        rootPath,
        siteName,
      );
      result.set(topFolderPath.value, aggregatedGroups);
    }

    return result;
  }

  private identifyTopFolders(
    items: AnySharepointItem[],
    rootPath: Smeared,
    siteName: Smeared,
  ): Smeared[] {
    const normalizedRootPath = createSmeared(`/${normalizeSlashes(rootPath.value)}`);

    return pipe(
      items,
      map((item) => getUniqueParentPathFromItem(item, rootPath, siteName)),
      filter((folderPath) => isTopFolder(folderPath, rootPath)),
      (paths) => [normalizedRootPath, ...paths],
      uniqueBy(prop('value')),
    );
  }

  private aggregateGroupPermissions(
    topFolderPath: Smeared,
    items: AnySharepointItem[],
    permissionsMap: Record<string, Membership[]>,
    rootPath: Smeared,
    siteName: Smeared,
  ): GroupMembership[] {
    const groupsMap = new Map<string, GroupMembership>();

    for (const item of items) {
      const itemPath = getUniquePathFromItem(item, rootPath, siteName);

      if (!this.isDescendantOf(itemPath, topFolderPath)) {
        continue;
      }

      const permissionsKey = buildIngestionItemKey(item);
      const permissions = permissionsMap[permissionsKey];

      if (isNullish(permissions)) {
        this.logger.warn(`No SharePoint permissions found for item with key ${permissionsKey}`);
        continue;
      }

      for (const permission of permissions) {
        if (permission.type === 'user') {
          continue;
        }

        const distinctId = groupDistinctId(permission);
        if (!groupsMap.has(distinctId)) {
          groupsMap.set(distinctId, permission);
        }
      }
    }

    return Array.from(groupsMap.values());
  }

  private isDescendantOf(itemPath: Smeared, topFolderPath: Smeared): boolean {
    return (
      itemPath.value === topFolderPath.value || itemPath.value.startsWith(`${topFolderPath.value}/`)
    );
  }
}
