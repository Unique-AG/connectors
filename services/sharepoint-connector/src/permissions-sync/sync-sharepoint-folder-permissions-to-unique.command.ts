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
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { ScopeAccess, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { buildIngestionItemKey, getUniquePathFromItem } from '../utils/sharepoint.util';
import { Membership, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  siteId: string;
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

  public constructor(
    private readonly uniqueScopesService: UniqueScopesService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async run(input: Input): Promise<void> {
    const { siteId, sharePoint, unique } = input;
    const logPrefix = `[Site: ${siteId}]`;
    this.logger.log(
      `${logPrefix} Starting folder permissions sync for ${unique.folders.length} Unique folders`,
    );

    const serviceUserId = await this.uniqueUsersService.getCurrentUserId();
    const sharePointDirectoriesPathMap = this.getSharePointDirectoriesPathMap(
      sharePoint.directories,
    );

    for (const uniqueFolder of unique.folders) {
      assert.ok(
        uniqueFolder.scopeAccess,
        'Unique folder scope accesses are required. Check if the folders were queried correctly' +
          ' from the Unique API.',
      );
      const loopLogPrefix = `${logPrefix}[Folder: ${uniqueFolder.id}]`;
      this.logger.debug(`${loopLogPrefix} Starting folder permissions processing`);
      const sharePointDirectory = sharePointDirectoriesPathMap[uniqueFolder.path];

      if (isNullish(sharePointDirectory)) {
        this.logger.warn(
          `${loopLogPrefix} No SharePoint directory found for path ${uniqueFolder.path}`,
        );
        continue;
      }

      const sharePointDirectoryKey = buildIngestionItemKey(sharePointDirectory);
      const sharePointPermissions = sharePoint.permissionsMap[sharePointDirectoryKey];
      if (isNullish(sharePointPermissions)) {
        this.logger.warn(
          `${loopLogPrefix} No SharePoint permissions found for key ${sharePointDirectoryKey}`,
        );
        continue;
      }

      const sharePointScopeAccesses = this.mapSharePointPermissionsToScopeAccesses(
        sharePointPermissions,
        unique.groupsMap,
        unique.usersMap,
      );

      const scopeAccessesToAdd = differenceWith(
        sharePointScopeAccesses,
        uniqueFolder.scopeAccess,
        isDeepEqual,
      );
      const scopeAccessesToRemove = differenceWith(
        uniqueFolder.scopeAccess,
        sharePointScopeAccesses,
        isDeepEqual,
      ).filter(
        // We need to ensure we do not remove the service user's access to folder. It won't be
        // present in SharePoint, but should be present in Unique, so we filter out any removals for
        // the service user.
        ({ entityType, entityId }) => !(entityType === 'USER' && entityId === serviceUserId),
      );

      this.logger.debug(
        `${loopLogPrefix} Adding ${scopeAccessesToAdd.length} and removing ` +
          `${scopeAccessesToRemove.length} scope accesses`,
      );
      if (scopeAccessesToAdd.length > 0) {
        await this.uniqueScopesService.createScopeAccesses(uniqueFolder.id, scopeAccessesToAdd);
      }
      if (scopeAccessesToRemove.length > 0) {
        await this.uniqueScopesService.deleteScopeAccesses(uniqueFolder.id, scopeAccessesToRemove);
      }
    }
  }

  private getSharePointDirectoriesPathMap(
    directories: SharepointDirectoryItem[],
  ): Record<string, SharepointDirectoryItem> {
    const rootScopeName = this.configService.get('unique.rootScopeName', {
      infer: true,
    });
    assert.ok(rootScopeName, 'rootScopeName must be configured');
    return indexBy(directories, (directory) => getUniquePathFromItem(directory, rootScopeName));
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
}
