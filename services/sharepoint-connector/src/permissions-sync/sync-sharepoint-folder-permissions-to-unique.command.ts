import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
  differenceWith,
  filter,
  indexBy,
  isDeepEqual,
  isNonNullish,
  isNullish,
  map,
  partition,
  pipe,
} from 'remeda';
import { Config } from '../config';
import { SharepointDirectoryItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { SharepointSyncContext } from '../sharepoint-synchronization/types';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { UniqueGroup } from '../unique-api/unique-groups/unique-groups.types';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { ScopeAccess, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { concealLogs, redact, smear } from '../utils/logging.util';
import {
  buildIngestionItemKey,
  getUniquePathFromItem,
  normalizeSlashes,
} from '../utils/sharepoint.util';
import { Membership, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  context: SharepointSyncContext;
  sharePoint: {
    directories: SharepointDirectoryItem[];
    permissionsMap: Record<string, Membership[]>;
  };
  unique: {
    folders: ScopeWithPath[];
    groupsMap: UniqueGroupsMap;
    usersMap: UniqueUsersMap;
  };
}

@Injectable()
export class SyncSharepointFolderPermissionsToUniqueCommand {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.shouldConcealLogs = concealLogs(this.configService);
  }

  public async run(input: Input): Promise<void> {
    const { context, sharePoint, unique } = input;
    const { siteId, rootPath, serviceUserId } = context;
    const logPrefix = `[Site: ${this.shouldConcealLogs ? smear(siteId) : siteId}]`;

    const rootGroup = await this.uniqueGroupsService.getRootGroup();
    if (!rootGroup) {
      this.logger.warn(`${logPrefix} Root group not found, skipping folder permissions sync`);
      return;
    }

    const sharePointDirectoriesPathMap = this.getSharePointDirectoriesPathMap(
      sharePoint.directories,
      rootPath,
    );

    const uniqueFoldersToProcess = unique.folders.filter(
      (folder) => !this.isParentOfRootFolder(folder.path, rootPath),
    );

    this.logger.log(
      `${logPrefix} Starting folder permissions sync for ${uniqueFoldersToProcess.length} Unique folders ` +
        `(filtered ${unique.folders.length - uniqueFoldersToProcess.length} parent folders)`,
    );

    for (const uniqueFolder of uniqueFoldersToProcess) {
      assert.ok(
        uniqueFolder.scopeAccess,
        'Unique folder scope accesses are required. Check if the folders were queried correctly' +
          ' from the Unique API.',
      );
      const loopLogPrefix = `${logPrefix}[Folder: ${uniqueFolder.id}]`;
      this.logger.debug(`${loopLogPrefix} Starting folder permissions processing`);

      const sharePointScopeAccesses = this.getSharePointScopeAccesses({
        logPrefix: loopLogPrefix,
        sharePoint: {
          directoriesPathMap: sharePointDirectoriesPathMap,
          permissionsMap: sharePoint.permissionsMap,
        },
        unique: {
          folder: uniqueFolder,
          rootGroup,
          groupsMap: unique.groupsMap,
          usersMap: unique.usersMap,
        },
        rootPath,
      });

      if (isNullish(sharePointScopeAccesses)) {
        continue;
      }

      await this.syncScopeAccesses({
        logPrefix: loopLogPrefix,
        sharePoint: {
          scopeAccesses: sharePointScopeAccesses,
        },
        unique: {
          folder: uniqueFolder,
          serviceUserId,
        },
      });
    }
  }

  private getSharePointDirectoriesPathMap(
    directories: SharepointDirectoryItem[],
    rootPath: string,
  ): Record<string, SharepointDirectoryItem> {
    return indexBy(directories, (directory) => getUniquePathFromItem(directory, rootPath));
  }

  private isParentOfRootFolder(path: string, rootPath: string): boolean {
    // A path is a parent of the root folder if the root path starts with the path
    // but they are not equal. We need to ensure we're comparing full path segments.
    // Example: if rootPath is /Top/Middle/IngestionRoot, then /Top and /Top/Middle are parents
    // but /Top/Middle/IngestionRoot is not a parent (it's the root itself)
    // and /Top/Middle/IngestionRoot/Folder is not a parent (it's a child)
    if (path === rootPath) {
      return false;
    }
    // Check if the normalized root path starts with this path followed by a slash
    return rootPath.startsWith(`${path}/`);
  }

  private isTopFolder(path: string, rootPath: string): boolean {
    // We're removing the root scope part, in case it has any slashes, to make it predictable.
    // Then we can check if the remaining part has at most 2 levels, because it indicates it is
    // either the site or the drive level.
    // Example: /RootScope/Site/Drive/Folder -> Site/Drive/Folder -> 3 levels -> false
    // Example: /RootScope/Site/Drive -> Site/Drive -> 2 levels -> true
    // Top folders don't have permissions fetched from SharePoint, so we use root group permission
    // instead.
    // The actual root path will not have replacement working for them because of no trailing slash,
    // so we handle it separately.
    if (path === rootPath) {
      return true;
    }
    return path.replace(`/${normalizeSlashes(rootPath)}/`, '').split('/').length <= 2;
  }

  private mapSharePointPermissionsToScopeAccesses(
    permissions: Membership[],
    uniqueGroupsMap: UniqueGroupsMap,
    uniqueUsersMap: UniqueUsersMap,
  ): ScopeAccess[] {
    const [userPermissions, groupPermissions] = partition(
      permissions,
      (permission) => permission.type === 'user',
    );

    const userScopeAccesses: ScopeAccess[] = pipe(
      userPermissions,
      map((permission) => uniqueUsersMap[permission.email]),
      filter(isNonNullish),
      map(
        (uniqueUserId) =>
          ({
            type: 'READ',
            entityId: uniqueUserId,
            entityType: 'USER',
          }) as const,
      ),
    );

    const groupScopeAccesses: ScopeAccess[] = pipe(
      groupPermissions,
      map((permission) => groupDistinctId(permission)),
      map((distinctId) => uniqueGroupsMap[distinctId]),
      filter(isNonNullish),
      map(
        (uniqueGroup) =>
          ({
            type: 'READ',
            entityId: uniqueGroup.id,
            entityType: 'GROUP',
          }) as const,
      ),
    );

    return [...userScopeAccesses, ...groupScopeAccesses];
  }

  private getSharePointScopeAccesses(input: {
    logPrefix: string;
    sharePoint: {
      directoriesPathMap: Record<string, SharepointDirectoryItem>;
      permissionsMap: Record<string, Membership[]>;
    };
    unique: {
      folder: ScopeWithPath;
      rootGroup: UniqueGroup;
      groupsMap: UniqueGroupsMap;
      usersMap: UniqueUsersMap;
    };
    rootPath: string;
  }): ScopeAccess[] | null {
    const { logPrefix, sharePoint, unique, rootPath } = input;
    const { folder, rootGroup } = unique;

    if (this.isTopFolder(folder.path, rootPath)) {
      this.logger.debug(
        `${logPrefix} Using root group permission for top folder at path ${folder.path}`,
      );
      return [
        {
          type: 'READ' as const,
          entityId: rootGroup.id,
          entityType: 'GROUP' as const,
        },
      ];
    }

    const sharePointDirectory = sharePoint.directoriesPathMap[folder.path];

    if (isNullish(sharePointDirectory)) {
      this.logger.warn(
        `${logPrefix} No SharePoint directory found for path ${this.shouldConcealLogs ? redact(folder.path) : folder.path}`,
      );
      return null;
    }

    const sharePointDirectoryKey = buildIngestionItemKey(sharePointDirectory);
    const sharePointPermissions = sharePoint.permissionsMap[sharePointDirectoryKey];
    if (isNullish(sharePointPermissions)) {
      this.logger.warn(
        `${logPrefix} No SharePoint permissions found for key ${sharePointDirectoryKey}`,
      );
      return null;
    }

    return this.mapSharePointPermissionsToScopeAccesses(
      sharePointPermissions,
      unique.groupsMap,
      unique.usersMap,
    );
  }

  private async syncScopeAccesses(input: {
    logPrefix: string;
    sharePoint: {
      scopeAccesses: ScopeAccess[];
    };
    unique: {
      folder: ScopeWithPath;
      serviceUserId: string;
    };
  }): Promise<void> {
    const { logPrefix, sharePoint, unique } = input;

    assert.ok(
      unique.folder.scopeAccess,
      'Unique folder scope accesses are required. Check if the folders were queried correctly' +
        ' from the Unique API.',
    );

    const scopeAccessesToAdd = differenceWith(
      sharePoint.scopeAccesses,
      unique.folder.scopeAccess,
      isDeepEqual,
    );
    const scopeAccessesToRemove = differenceWith(
      unique.folder.scopeAccess,
      sharePoint.scopeAccesses,
      isDeepEqual,
    ).filter(
      // We need to ensure we do not remove the service user's access to folder. It won't be
      // present in SharePoint, but should be present in Unique, so we filter out any removals for
      // the service user.
      ({ entityType, entityId }) => !(entityType === 'USER' && entityId === unique.serviceUserId),
    );

    this.logger.debug(
      `${logPrefix} Adding ${scopeAccessesToAdd.length} and removing ` +
        `${scopeAccessesToRemove.length} scope accesses`,
    );
    if (scopeAccessesToAdd.length > 0) {
      await this.uniqueScopesService.createScopeAccesses(unique.folder.id, scopeAccessesToAdd);
    }
    if (scopeAccessesToRemove.length > 0) {
      await this.uniqueScopesService.deleteScopeAccesses(unique.folder.id, scopeAccessesToRemove);
    }
  }
}
