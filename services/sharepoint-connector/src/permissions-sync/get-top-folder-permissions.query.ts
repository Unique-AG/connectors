import { Injectable, Logger } from '@nestjs/common';
import { filter, isNullish, map, pipe, unique } from 'remeda';
import {
  AnySharepointItem,
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { normalizeSlashes } from '../utils/paths.util';
import { buildIngestionItemKey, getUniquePathFromItem } from '../utils/sharepoint.util';
import { GroupMembership, Membership } from './types';
import { groupDistinctId, isTopFolder } from './utils';

interface Input {
  items: SharepointContentItem[];
  directories: SharepointDirectoryItem[];
  permissionsMap: Record<string, Membership[]>;
  rootPath: string;
}

@Injectable()
export class GetTopFolderPermissionsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public run(input: Input): Map<string, GroupMembership[]> {
    const { items, directories, permissionsMap, rootPath } = input;
    const allItems: AnySharepointItem[] = [...items, ...directories];

    const topFolders = this.identifyTopFolders(allItems, rootPath);
    const result = new Map<string, GroupMembership[]>();

    for (const topFolderPath of topFolders) {
      const aggregatedGroups = this.aggregateGroupPermissions(
        topFolderPath,
        allItems,
        permissionsMap,
        rootPath,
      );
      result.set(topFolderPath, aggregatedGroups);
    }

    return result;
  }

  private identifyTopFolders(items: AnySharepointItem[], rootPath: string): string[] {
    const normalizedRootPath = `/${normalizeSlashes(rootPath)}`;

    return pipe(
      items,
      map((item) => getUniquePathFromItem(item, rootPath)),
      filter((folderPath) => isTopFolder(folderPath, rootPath)),
      (paths) => [normalizedRootPath, ...paths],
      unique(),
    );
  }

  private aggregateGroupPermissions(
    topFolderPath: string,
    items: AnySharepointItem[],
    permissionsMap: Record<string, Membership[]>,
    rootPath: string,
  ): GroupMembership[] {
    const groupsMap = new Map<string, GroupMembership>();

    for (const item of items) {
      const itemPath = getUniquePathFromItem(item, rootPath);

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

  private isDescendantOf(itemPath: string, topFolderPath: string): boolean {
    return itemPath === topFolderPath || itemPath.startsWith(`${topFolderPath}/`);
  }
}
