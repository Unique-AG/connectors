import { Injectable, Logger } from '@nestjs/common';
import { filter, flat, indexBy, mapKeys, mapValues, pipe, prop, uniqueBy, values } from 'remeda';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX } from '../unique-api/unique-groups/unique-groups.consts';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FetchGraphPermissionsMapQuery } from './fetch-graph-permissions-map.query';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import { SyncSharepointFilesPermissionsToUniqueCommand } from './sync-sharepoint-files-permissions-to-unique.command';
import { SyncSharepointGroupsToUniqueCommand } from './sync-sharepoint-groups-to-unique.command';
import { UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  siteId: string;
  sharePoint: {
    items: SharepointContentItem[];
    directories: SharepointDirectoryItem[];
  };
  unique: {
    folders: (Scope & { path: string })[];
  };
}

@Injectable()
export class PermissionsSyncService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly fetchGraphPermissionsMapQuery: FetchGraphPermissionsMapQuery,
    private readonly fetchGroupsWithMembershipsQuery: FetchGroupsWithMembershipsQuery,
    private readonly syncSharepointGroupsToUniqueCommand: SyncSharepointGroupsToUniqueCommand,
    private readonly syncSharepointFilesPermissionsToUniqueCommand: SyncSharepointFilesPermissionsToUniqueCommand,
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly uniqueUsersService: UniqueUsersService,
  ) {}

  public async syncPermissionsForSite(input: Input): Promise<void> {
    const { siteId, sharePoint, unique: _unique } = input;
    const logPrefix = `[SiteId: ${siteId}]`;
    this.logger.log(
      `${logPrefix} Starting permissions fetching for ${sharePoint.items.length} items and ` +
        `${sharePoint.directories.length} directories`,
    );
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.fetchGraphPermissionsMapQuery.run(siteId, sharePoint.items);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${sharePoint.items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );

    const uniqueGroupPermissions = pipe(
      permissionsMap,
      values(),
      flat(),
      filter((permission) => permission.type !== 'user'),
      uniqueBy(groupDistinctId),
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

    const uniqueUsersMap = await this.getUniqueUsersMap();
    const uniqueGroupsMap = await this.getUniqueGroupsMap();

    this.logger.log(
      `${logPrefix} Found ${Object.keys(uniqueGroupsMap).length} unique groups and ${Object.keys(uniqueUsersMap).length} unique users`,
    );

    const { updatedUniqueGroupsMap } = await this.syncSharepointGroupsToUniqueCommand.run({
      sharePointGroupsMap: groupsWithMemberships,
      uniqueGroupsMap,
      uniqueUsersMap,
    });

    this.logger.log(
      `${logPrefix} Synced ${Object.keys(updatedUniqueGroupsMap).length} resulting unique groups`,
    );

    await this.syncSharepointFilesPermissionsToUniqueCommand.run({
      siteId,
      permissionsMap,
      uniqueGroupsMap: updatedUniqueGroupsMap,
      uniqueUsersMap,
    });

    this.logger.log(`${logPrefix} Synced file permissions to Unique`);
  }

  private async getUniqueUsersMap(): Promise<UniqueUsersMap> {
    return pipe(
      await this.uniqueUsersService.listAllUsers(),
      indexBy(prop('email')),
      mapValues(prop('id')),
    );
  }

  private async getUniqueGroupsMap(): Promise<UniqueGroupsMap> {
    return pipe(
      await this.uniqueGroupsService.listAllGroups(),
      indexBy(prop('externalId')),
      mapKeys((groupExternalId) =>
        groupExternalId.replace(
          new RegExp(`^${SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX}`),
          '',
        ),
      ),
    );
  }
}
