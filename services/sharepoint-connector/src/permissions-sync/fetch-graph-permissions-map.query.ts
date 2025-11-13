import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { isNonNullish } from 'remeda';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import {
  SimpleIdentitySet,
  SimplePermission,
} from '../microsoft-apis/graph/types/sharepoint.types';
import type { AnySharepointItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { buildIngestionItemKey } from '../utils/sharepoint.util';
import { Membership } from './types';
import { ALL_USERS_GROUP_ID_PREFIX, normalizeMsGroupId, OWNERS_SUFFIX } from './utils';

// We rename the type for clarity. we use the same stucture for permissions on files/folders as well
// as memberships of groups. These are the same structures, so for the ease of code reading we ranem
// the local type name.
type Permission = Membership;
type PermissionsMap = Record<string, Permission[]>;
type PermissionsFetcher = Record<AnySharepointItem['itemType'], () => Promise<SimplePermission[]>>;

@Injectable()
export class FetchGraphPermissionsMapQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphApiService: GraphApiService) {}

  public async run(siteId: string, items: AnySharepointItem[]): Promise<PermissionsMap> {
    const siteWebUrl = await this.graphApiService.getSiteWebUrl(siteId);
    const siteName = siteWebUrl.split('/').pop();
    assert.ok(siteName, `Site name not found for site ${siteId}`);

    const permissionsMap: PermissionsMap = {};
    // TODO: Once API is batched and parallelised, change this to use Promise.allSettled.
    for (const item of items) {
      const permissionsFetcher: PermissionsFetcher = {
        driveItem: () => this.graphApiService.getDriveItemPermissions(item.driveId, item.item.id),
        listItem: () =>
          this.graphApiService.getListItemPermissions(siteId, item.driveId, item.item.id),
        directory: () => this.graphApiService.getDriveItemPermissions(item.driveId, item.item.id),
      };

      permissionsMap[buildIngestionItemKey(item)] = this.mapSharePointPermissionsToOurPermissions(
        await permissionsFetcher[item.itemType](),
        siteName,
      );
    }
    return permissionsMap;
  }

  private mapSharePointPermissionsToOurPermissions(
    simplePermissions: SimplePermission[],
    siteName: string,
  ): Permission[] {
    return simplePermissions.flatMap((permission) => {
      if (isNonNullish(permission.grantedToV2)) {
        const itemPermission = this.mapSharePointIdentitySetToOurPermission(
          permission.grantedToV2,
          siteName,
        );
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
          .map((simpleIdentitySet) =>
            this.mapSharePointIdentitySetToOurPermission(simpleIdentitySet, siteName),
          )
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

  private mapSharePointIdentitySetToOurPermission(
    simpleIdentitySet: SimpleIdentitySet,
    siteName: string,
  ): Permission | null {
    if (isNonNullish(simpleIdentitySet.group) && isNonNullish(simpleIdentitySet.siteUser)) {
      const groupId = normalizeMsGroupId(simpleIdentitySet.group.id);
      // TODO: This is basically the case of "Everyone except external users". How are we supposed
      //       to handle this case? For now we return null to skip it. Does it happen outside of
      //       SharePoint permissions visible in Site Groups? If it doesn't, we can safely ignore
      //       it here.
      if (groupId.startsWith(ALL_USERS_GROUP_ID_PREFIX)) {
        return null;
      }

      const isOwners = simpleIdentitySet.siteUser.loginName?.endsWith(OWNERS_SUFFIX);
      return {
        // Login name of the group looks like
        // c:0o.c|federateddirectoryclaimprovider|838f7d2d-BBBB-AAAA-DDDD-7dd9d399aff7_o
        // or
        // c:0o.c|federateddirectoryclaimprovider|838f7d2d-BBBB-AAAA-DDDD-7dd9d399aff7
        // Presence of _o suffix indicates the owners of the group as opposed to the members
        type: `group${isOwners ? 'Owners' : 'Members'}`,
        id: groupId,
        name: simpleIdentitySet.group.displayName,
      };
    }

    if (isNonNullish(simpleIdentitySet.siteGroup)) {
      return {
        type: 'siteGroup',
        id: `${siteName}|${simpleIdentitySet.siteGroup.id}`,
        name: simpleIdentitySet.siteGroup.displayName,
      };
    }

    if (isNonNullish(simpleIdentitySet.user) && isNonNullish(simpleIdentitySet.siteUser)) {
      return {
        type: 'user',
        email: simpleIdentitySet.user.email,
      };
    }

    this.logger.warn(`Unknown identity set: ${Object.keys(simpleIdentitySet).join(', ')}`);
    return null;
  }
}
