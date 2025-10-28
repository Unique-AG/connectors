import { Injectable, Logger } from '@nestjs/common';
import { isNonNullish } from 'remeda';
import { GraphApiService } from '../msgraph/graph-api.service';
import { SimpleIdentitySet, SimplePermission } from '../msgraph/types/sharepoint.types';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { elapsedSecondsLog } from '../utils/timing.util';

const OWNERS_SUFFIX = '_o';

type ItemPermission =
  | {
      type: 'user';
      id: string;
      email: string;
    }
  | {
      type: 'siteGroup';
      id: string;
      name: string;
    }
  | {
      type: 'groupMembers';
      id: string;
      name: string;
    }
  | {
      type: 'groupOwners';
      id: string;
      name: string;
    };

@Injectable()
export class PermissionsSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphApiService: GraphApiService) {}

  public async syncPermissionsForSite(
    siteId: string,
    items: SharepointContentItem[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    this.logger.log(`${logPrefix} Starting permissions fetching for ${items.length} items`);
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.getPermissionsMap(siteId, items);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );
    this.logger.log(`${logPrefix} Permissions map length: ${Object.keys(permissionsMap).length}`);
  }

  private async getPermissionsMap(
    siteId: string,
    items: SharepointContentItem[],
  ): Promise<Record<string, ItemPermission[]>> {
    const permissionsMap: Record<string, ItemPermission[]> = {};
    // TODO: Once API is batched and parallelised, change this to use Promise.allSettled.
    for (const item of items) {
      if (item.itemType === 'driveItem') {
        const permissions = await this.graphApiService.getDriveItemPermissions(
          item.driveId,
          item.item.id,
        );
        permissionsMap[`${item.driveId}/${item.item.id}`] =
          this.mapSimplePermissionsToItemPermissions(permissions);
      } else if (item.itemType === 'listItem') {
        const permissions = await this.graphApiService.getListItemPermissions(
          siteId,
          item.driveId,
          item.item.id,
        );
        permissionsMap[`${item.driveId}/${item.item.id}`] =
          this.mapSimplePermissionsToItemPermissions(permissions);
      }
    }
    return permissionsMap;
  }

  private mapSimplePermissionsToItemPermissions(
    simplePermissions: SimplePermission[],
  ): ItemPermission[] {
    return simplePermissions.flatMap((permission) => {
      if (isNonNullish(permission.grantedToV2)) {
        const itemPermission = this.mapSimpleIdentitySetToItemPermission(permission.grantedToV2);
        if (isNonNullish(itemPermission)) {
          return [itemPermission];
        }
      }

      if (isNonNullish(permission.grantedToIdentitiesV2)) {
        // Typical case with sharing link without any particular person included
        if (permission.grantedToIdentitiesV2.length === 0) {
          return [];
        }

        const itemPermissions = permission.grantedToIdentitiesV2
          .map(this.mapSimpleIdentitySetToItemPermission.bind(this))
          .filter(isNonNullish);
        if (itemPermissions.length > 0) {
          return itemPermissions;
        }
      }

      this.logger.warn(
        `No parsable permissions for permission ${permission.id}: ${JSON.stringify(permission, null, 4)}`,
      );
      return [];
    });
  }

  private mapSimpleIdentitySetToItemPermission(
    simpleIdentitySet: SimpleIdentitySet,
  ): ItemPermission | null {
    if (isNonNullish(simpleIdentitySet.group) && isNonNullish(simpleIdentitySet.siteUser)) {
      const isOwners = simpleIdentitySet.siteUser.loginName?.endsWith(OWNERS_SUFFIX);
      return {
        // Login name of the group looks like
        // c:0o.c|federateddirectoryclaimprovider|838f7d2d-BBBB-AAAA-DDDD-7dd9d399aff7_o
        // or
        // c:0o.c|federateddirectoryclaimprovider|838f7d2d-BBBB-AAAA-DDDD-7dd9d399aff7
        // Presence of _o suffix indicates the owners of the group as opposed to the members
        type: `group${isOwners ? 'Owners' : 'Members'}`,
        id: simpleIdentitySet.group.id,
        name: simpleIdentitySet.group.displayName,
      };
    }

    if (isNonNullish(simpleIdentitySet.siteGroup)) {
      return {
        type: 'siteGroup',
        id: simpleIdentitySet.siteGroup.id,
        name: simpleIdentitySet.siteGroup.displayName,
      };
    }

    if (isNonNullish(simpleIdentitySet.user) && isNonNullish(simpleIdentitySet.siteUser)) {
      return {
        type: 'user',
        id: simpleIdentitySet.user.id,
        email: simpleIdentitySet.user.email,
      };
    }

    this.logger.warn(`Unknown identity set: ${Object.keys(simpleIdentitySet).join(', ')}`);
    return null;
  }
}
