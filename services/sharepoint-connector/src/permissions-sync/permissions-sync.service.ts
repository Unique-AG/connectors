import { Injectable, Logger } from '@nestjs/common';
import { filter, flat, pipe, uniqueBy, values } from 'remeda';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FetchGraphPermissionsMapQuery } from './fetch-graph-permissions-map.query';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import { groupUniqueId } from './utils';

@Injectable()
export class PermissionsSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly fetchGraphPermissionsMapQuery: FetchGraphPermissionsMapQuery,
    private readonly fetchGroupsWithMembershipsQuery: FetchGroupsWithMembershipsQuery,
  ) {}

  public async syncPermissionsForSite(
    siteId: string,
    items: SharepointContentItem[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}] `;
    this.logger.log(`${logPrefix} Starting permissions fetching for ${items.length} items`);
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.fetchGraphPermissionsMapQuery.run(siteId, items);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );
    this.logger.log(`${logPrefix} Permissions map length: ${Object.keys(permissionsMap).length}`);

    const uniqueGroupPermissions = pipe(
      permissionsMap,
      values(),
      flat(),
      filter((permission) => permission.type !== 'user'),
      uniqueBy(groupUniqueId),
    );
    const groupsWithMemberships = await this.fetchGroupsWithMembershipsQuery.run(
      siteId,
      uniqueGroupPermissions,
    );

    this.logger.log(`${logPrefix} Groups found: ${Object.keys(groupsWithMemberships).length}`);
  }
}
