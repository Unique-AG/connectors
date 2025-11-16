import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { filter, flat, indexBy, mapKeys, mapValues, pipe, prop, uniqueBy, values } from 'remeda';
import { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX } from '../unique-api/unique-groups/unique-groups.consts';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { elapsedSecondsLog } from '../utils/timing.util';
import { FetchGraphPermissionsMapQuery, PermissionsMap } from './fetch-graph-permissions-map.query';
import { FetchGroupsWithMembershipsQuery } from './fetch-groups-with-memberships.query';
import { SyncSharepointFilesPermissionsToUniqueCommand } from './sync-sharepoint-files-permissions-to-unique.command';
import { SyncSharepointFolderPermissionsToUniqueCommand } from './sync-sharepoint-folder-permissions-to-unique.command';
import { SyncSharepointGroupsToUniqueCommand } from './sync-sharepoint-groups-to-unique.command';
import { SharePointGroupsMap, UniqueGroupsMap, UniqueUsersMap } from './types';
import { groupDistinctId } from './utils';

interface Input {
  siteId: string;
  sharePoint: {
    items: SharepointContentItem[];
    directories: SharepointDirectoryItem[];
  };
  unique: {
    // We will not pass unique folders for flat ingestion mode
    folders: ScopeWithPath[] | null;
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
    private readonly syncSharepointFolderPermissionsToUniqueCommand: SyncSharepointFolderPermissionsToUniqueCommand,
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly uniqueUsersService: UniqueUsersService,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public async syncPermissionsForSite(input: Input): Promise<void> {
    const { siteId, sharePoint, unique } = input;
    const logPrefix = `[SiteId: ${siteId}]`;
    this.logger.log(
      `${logPrefix} Starting permissions fetching for ${sharePoint.items.length} items and ` +
        `${sharePoint.directories.length} directories`,
    );
    const permissionsFetchStartTime = Date.now();
    const permissionsMap = await this.fetchGraphPermissionsMapQuery.run(siteId, [
      ...sharePoint.items,
      ...sharePoint.directories,
    ]);
    this.logger.log(
      `${logPrefix} Fetched permissions for ${sharePoint.items.length} items in ${elapsedSecondsLog(permissionsFetchStartTime)}`,
    );

    const groupsWithMembershipsMap = await this.fetchGroupsWithMembershipsForSite(
      siteId,
      permissionsMap,
    );

    this.logger.log(
      `${logPrefix} Fetched ${Object.keys(groupsWithMembershipsMap).length} groups with memberships`,
    );

    const uniqueUsersMap = await this.getUniqueUsersMap();
    const uniqueGroupsMap = await this.getUniqueGroupsMap();

    this.logger.log(
      `${logPrefix} Found ${Object.keys(uniqueGroupsMap).length} unique groups and ${Object.keys(uniqueUsersMap).length} unique users`,
    );

    const { updatedUniqueGroupsMap } = await this.syncSharepointGroupsToUniqueCommand.run({
      siteId,
      sharePoint: { groupsMap: groupsWithMembershipsMap },
      unique: { groupsMap: uniqueGroupsMap, usersMap: uniqueUsersMap },
    });

    this.logger.log(
      `${logPrefix} Synced ${Object.keys(updatedUniqueGroupsMap).length} resulting unique groups`,
    );

    await this.syncSharepointFilesPermissionsToUniqueCommand.run({
      siteId,
      sharePoint: { permissionsMap },
      unique: { groupsMap: updatedUniqueGroupsMap, usersMap: uniqueUsersMap },
    });

    const ingestionMode = this.configService.get('unique.ingestionMode', { infer: true });

    if (ingestionMode === IngestionMode.Recursive) {
      assert.ok(
        unique.folders,
        `[Site: ${siteId}] Folders are required for recursive ingestion mode`,
      );
      await this.syncSharepointFolderPermissionsToUniqueCommand.run({
        siteId,
        sharePoint: { directories: sharePoint.directories, permissionsMap },
        unique: {
          folders: unique.folders,
          groupsMap: updatedUniqueGroupsMap,
          usersMap: uniqueUsersMap,
        },
      });
    }

    this.logger.log(`${logPrefix} Synced file permissions to Unique`);
  }

  private async fetchGroupsWithMembershipsForSite(
    siteId: string,
    permissionsMap: PermissionsMap,
  ): Promise<SharePointGroupsMap> {
    const logPrefix = `[Site: ${siteId}]`;
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
    return await this.fetchGroupsWithMembershipsQuery.run(siteId, uniqueGroupPermissions);
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
