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
import { Smeared } from '../utils/smeared';
import { Membership } from './types';
import { ALL_USERS_GROUP_ID_PREFIX, normalizeMsGroupId, OWNERS_SUFFIX } from './utils';

// We rename the type for clarity. we use the same stucture for permissions on files/folders as well
// as memberships of groups. These are the same structures, so for the ease of code reading we ranem
// the local type name.
type Permission = Membership;
export type PermissionsMap = Record<string, Permission[]>;
type PermissionsFetcher = Record<AnySharepointItem['itemType'], () => Promise<SimplePermission[]>>;

@Injectable()
export class FetchGraphPermissionsMapQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphApiService: GraphApiService) {}

  public async run(
    items: AnySharepointItem[],
    siteNameBySiteId: ReadonlyMap<string, Smeared>,
  ): Promise<PermissionsMap> {
    const permissionsMap: PermissionsMap = {};
    // TODO: Once API is batched and parallelised, change this to use Promise.allSettled.
    for (const item of items) {
      const itemSiteName = siteNameBySiteId.get(item.siteId.value);
      assert.ok(itemSiteName, `Site name for site ${item.siteId} not found`);
      const permissionsFetcher: PermissionsFetcher = {
        driveItem: () => this.graphApiService.getDriveItemPermissions(item.driveId, item.item.id),
        listItem: () =>
          this.graphApiService.getListItemPermissions(item.siteId, item.driveId, item.item.id),
        directory: () => this.graphApiService.getDriveItemPermissions(item.driveId, item.item.id),
      };

      const sharePointPermissions = await permissionsFetcher[item.itemType]();
      permissionsMap[buildIngestionItemKey(item)] = this.mapSharePointPermissionsToOurPermissions(
        sharePointPermissions,
        item.siteId,
        itemSiteName,
        item.item.id,
      );
    }
    return permissionsMap;
  }

  private mapSharePointPermissionsToOurPermissions(
    simplePermissions: SimplePermission[],
    siteId: Smeared,
    siteName: Smeared,
    itemId: string,
  ): Permission[] {
    return simplePermissions.flatMap((permission) => {
      if (isNonNullish(permission.grantedToV2)) {
        const itemPermission = this.mapSharePointIdentitySetToOurPermission(
          permission.grantedToV2,
          siteId,
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
            this.mapSharePointIdentitySetToOurPermission(simpleIdentitySet, siteId, siteName),
          )
          .filter(isNonNullish);
        if (itemPermissions.length > 0) {
          return itemPermissions;
        }
      }
      // we do not want to log the full permissions object because it contains sensitive data
      const permissionInfo = {
        itemId,
        id: permission.id,
        grantedToIdentitiesV2: permission.grantedToIdentitiesV2?.map(
          (simpleIdentitySet: SimpleIdentitySet) => {
            const redactedIdentity: Record<string, unknown> = {};
            Object.keys(simpleIdentitySet).forEach((key) => {
              // We need to type the key and the identityValue else typescript will complain
              const typedKey = key as keyof SimpleIdentitySet;
              const identityValue = simpleIdentitySet[typedKey] as
                | Record<string, unknown>
                | undefined;
              redactedIdentity[typedKey] = {
                id: identityValue?.id,
                '@odata.type': identityValue?.['@odata.type'],
              };
            });
            return redactedIdentity;
          },
        ),
      };

      this.logger.warn(
        `No parsable permissions for permission ${permission.id}: ${JSON.stringify(
          permissionInfo,
          null,
          4,
        )}`,
      );
      return [];
    });
  }

  private mapSharePointIdentitySetToOurPermission(
    simpleIdentitySet: SimpleIdentitySet,
    siteId: Smeared,
    siteName: Smeared,
  ): Permission | null {
    if (isNonNullish(simpleIdentitySet.group) && isNonNullish(simpleIdentitySet.siteUser)) {
      const groupId = normalizeMsGroupId(simpleIdentitySet.group.id);
      // We skip "Everyone except external users" group because we wuld rather err on the side of
      // caution and not include any wildcard groups.
      if (groupId.startsWith(ALL_USERS_GROUP_ID_PREFIX)) {
        return null;
      }

      const isOwners = simpleIdentitySet.siteUser.loginName?.endsWith(OWNERS_SUFFIX);
      return {
        siteId,
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
        siteId,
        type: 'siteGroup',
        id: `${siteName.value}|${simpleIdentitySet.siteGroup.id}`,
        name: simpleIdentitySet.siteGroup.displayName,
      };
    }

    if (isNonNullish(simpleIdentitySet.user) || isNonNullish(simpleIdentitySet.siteUser)) {
      let userEmail: string | undefined;

      if (isNonNullish(simpleIdentitySet.user)) {
        userEmail = simpleIdentitySet.user.email;
      }

      // We handle the case where only siteUser is present, because such case may occur when user is
      // deleted from Entra but they still have old sharing permissions in SharePoint.
      // This section is not handled with `else if` because `user` may be an object but email may be
      // missing there, and we may fall back on the loginName from `siteUser`.
      if (!userEmail && isNonNullish(simpleIdentitySet.siteUser)) {
        // In some specific cases, that are rather unclear, there may be no email in the user object,
        // but it may be present in the siteUser object, as part of the loginName which looks like
        // "i:0#.f|membership|user@dogfood.industries".
        userEmail =
          simpleIdentitySet.siteUser.email || simpleIdentitySet.siteUser.loginName.split('|').pop();
      }

      // Ensure the value resembles an email and we did not get something else from loginName split.
      if (userEmail?.includes('@')) {
        return { type: 'user', email: userEmail };
      }
    }

    this.logger.warn(`Unknown identity set: ${Object.keys(simpleIdentitySet).join(', ')}`);
    return null;
  }
}
