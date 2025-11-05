import { Injectable, Logger } from '@nestjs/common';
import { filter, flat, pipe, uniqueBy, values } from 'remeda';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
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
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly uniqueUsersService: UniqueUsersService,
  ) {}

  public async syncPermissionsForSite(
    siteId: string,
    items: SharepointContentItem[],
  ): Promise<void> {
    const logPrefix = `[SiteId: ${siteId}]`;
    this.logger.log(`${logPrefix} Starting permissions fetching for ${items.length} items`);
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.fetchGraphPermissionsMapQuery.run(siteId, items);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );

    const uniqueGroupPermissions = pipe(
      permissionsMap,
      values(),
      flat(),
      filter((permission) => permission.type !== 'user'),
      uniqueBy(groupUniqueId),
    );
    this.logger.log(
      `${logPrefix} Fetching groups with memberships from SharePoint & Graph APIs for ` +
        `${uniqueGroupPermissions.length} unique group permissions`,
    );
    const groupsWithMemberships = await this.fetchGroupsWithMembershipsQuery.run(
      siteId,
      uniqueGroupPermissions,
    );
    this.logger.log(`${logPrefix} Groups with memberships fetched successfully`);

    this.logger.log(
      `${logPrefix} Found ${Object.keys(groupsWithMemberships).length} groups with memberships`,
    );

    const uniqueGroups = await this.uniqueGroupsService.listAllGroups();
    const uniqueUsers = await this.uniqueUsersService.listAllUsers();

    this.logger.log(
      `${logPrefix} Found ${uniqueGroups.length} unique groups and ${uniqueUsers.length} unique users`,
    );
  }
}
