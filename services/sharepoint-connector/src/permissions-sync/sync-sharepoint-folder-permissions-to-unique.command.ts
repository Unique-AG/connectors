import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
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
  prop,
} from 'remeda';
import { SharepointDirectoryItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { Scope, ScopeAccess } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { buildIngestionItemKey } from '../utils/sharepoint.util';
import { Membership, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  siteId: string;
  sharePoint: {
    directories: SharepointDirectoryItem[];
    permissionsMap: Record<string, Membership[]>;
  };
  unique: {
    folders: (Scope & { path: string })[];
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
  ) {}

  public async run(input: Input): Promise<void> {
    const { siteId, sharePoint, unique } = input;
    const logPrefix = `[Site: ${siteId}]`;
    this.logger.log(
      `${logPrefix} Starting folder permissions sync for ${unique.folders.length} Uniquefolders`,
    );

    // We need current user id to be sure to not remove their access to folder, because it won't be
    // present in SharePoint, but should be present in Unique.
    const currentUserId = await this.uniqueUsersService.getCurrentUserId();
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

      const uniqueScopeAccesses = uniqueFolder.scopeAccess.filter(
        (scopeAccess) =>
          scopeAccess.entityType === 'USER' && scopeAccess.entityId === 'service-user',
      );

      const scopeAccessesToAdd = differenceWith(
        sharePointScopeAccesses,
        uniqueScopeAccesses,
        isDeepEqual,
      );
      const scopeAccessesToRemove = differenceWith(
        uniqueScopeAccesses,
        sharePointScopeAccesses,
        isDeepEqual,
      ).filter(
        ({ entityType, entityId }) => !(entityType === 'USER' && entityId === currentUserId),
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
    // TODO: Once Lorand's PR is merged, we have to use whatever util he uses to get path out of
    //       directory sharepoint item to match it against path from unique folders.
    return indexBy(directories, prop('item', 'listItem', 'webUrl'));
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
