import { Inject, Injectable, Logger } from '@nestjs/common';
import { type Counter } from '@opentelemetry/api';
import { difference, filter, isNonNullish, map, pickBy, pipe } from 'remeda';
import { SPC_PERMISSIONS_SYNC_GROUP_OPERATIONS_TOTAL } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { UniqueGroupWithMembers } from '../unique-api/unique-groups/unique-groups.types';
import { getSharepointConnectorGroupExternalId } from '../unique-api/unique-groups/unique-groups.utils';
import { createSmeared, Smeared } from '../utils/smeared';
import {
  GroupDistinctId,
  SharePointGroupsMap,
  SharepointGroupWithMembers,
  UniqueGroupsMap,
  UniqueUsersMap,
} from './types';

interface Input {
  siteId: Smeared;
  sharePoint: {
    groupsMap: SharePointGroupsMap;
  };
  unique: {
    groupsMap: UniqueGroupsMap;
    usersMap: UniqueUsersMap;
  };
}

// Normally we wouldn't return anything from command, but we don't want to re-fetch data form
// external services after the command is executed, so we instead return the updated data that we
// will receive from mutations.
interface Output {
  updatedUniqueGroupsMap: UniqueGroupsMap;
}

@Injectable()
export class SyncSharepointGroupsToUniqueCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueGroupsService: UniqueGroupsService,
    private readonly graphApiService: GraphApiService,
    @Inject(SPC_PERMISSIONS_SYNC_GROUP_OPERATIONS_TOTAL)
    private readonly spcPermissionsSyncGroupOperationsTotal: Counter,
  ) {}

  public async run(input: Input): Promise<Output> {
    const { siteId, sharePoint, unique } = input;

    const logPrefix = `[Site: ${siteId}]`;

    const siteName = await this.graphApiService.getSiteName(siteId);
    const updatedUniqueGroupsMap: Record<GroupDistinctId, UniqueGroupWithMembers | null> = {};

    const sharePointGroups = Object.values(sharePoint.groupsMap);
    this.logger.log(`${logPrefix} Syncing ${sharePointGroups.length} sharepoint groups`);
    const groupsSyncStats: Record<
      'created' | 'updated' | 'deleted' | 'skipped' | 'unchanged',
      number
    > = {
      created: 0,
      updated: 0,
      deleted: 0,
      skipped: 0,
      unchanged: 0,
    };

    for (const sharePointGroup of sharePointGroups) {
      const groupLogPrefix = `[Group: ${createSmeared(sharePointGroup.id)}]`;
      this.logger.debug(
        `${groupLogPrefix} Syncing sharepoint group ${createSmeared(sharePointGroup.displayName)}`,
      );

      const correspondingUniqueGroup = unique.groupsMap[sharePointGroup.id];
      if (!correspondingUniqueGroup) {
        const newUniqueGroup = await this.createUniqueGroup(
          siteId,
          siteName,
          sharePointGroup,
          unique.usersMap,
        );
        updatedUniqueGroupsMap[sharePointGroup.id] = newUniqueGroup;
        if (newUniqueGroup) {
          groupsSyncStats.created++;
          this.logger.debug(`${groupLogPrefix} Created new Unique Group`);
        } else {
          groupsSyncStats.skipped++;
          this.logger.debug(`${groupLogPrefix} Skipped Unique Group creation due to no members`);
        }
        continue;
      }

      const [didUpdate, updatedUniqueGroup] = await this.syncExistingUniqueGroup(
        correspondingUniqueGroup,
        siteName,
        sharePointGroup,
        unique.usersMap,
      );
      if (didUpdate) {
        updatedUniqueGroupsMap[sharePointGroup.id] = updatedUniqueGroup;
        if (updatedUniqueGroup) {
          groupsSyncStats.updated++;
          this.logger.debug(`${groupLogPrefix} Updated Unique Group`);
        } else {
          groupsSyncStats.deleted++;
          this.logger.debug(`${groupLogPrefix} Deleted Unique Group due to no members`);
        }
        continue;
      }

      groupsSyncStats.unchanged++;
      this.logger.debug(`${groupLogPrefix} No changes to Unique Group`);
      updatedUniqueGroupsMap[sharePointGroup.id] = correspondingUniqueGroup;
    }

    // TODO: Uncomment this once https://unique-ch.atlassian.net/browse/UN-15272 is resolved.
    //       We've encountered a problem where scope accesses are not cleared correctly resulting in
    //       orphaned scope accesses that we could no longer delete due to access checks.
    // const missingGroupDistinctIds = difference(
    //   keys(unique.groupsMap),
    //   keys(updatedUniqueGroupsMap),
    // );
    //
    // this.logger.log(
    //   `${logPrefix} Deleting ${missingGroupDistinctIds.length} missing unique groups`,
    // );
    // for (const groupDistinctId of missingGroupDistinctIds) {
    //   const missingGroup =
    //     unique.groupsMap[groupDistinctId] ??
    //     assert.fail(`Missing group ${groupDistinctId} in unique groups map`);
    //   await this.uniqueGroupsService.deleteGroup(missingGroup.id);
    //   groupsSyncStats.deleted++;
    // }

    this.logger.log(
      `${logPrefix} Synced ${sharePointGroups.length} sharepoint groups:\n` +
        `    Created:   ${groupsSyncStats.created} groups\n` +
        `    Updated:   ${groupsSyncStats.updated} groups\n` +
        `    Deleted:   ${groupsSyncStats.deleted} groups\n` +
        `    Skipped:   ${groupsSyncStats.skipped} groups\n` +
        `    Unchanged: ${groupsSyncStats.unchanged} groups`,
    );

    const syncStatsEntries = Object.entries(groupsSyncStats).filter(([_, count]) => count > 0);
    for (const [operation, count] of syncStatsEntries) {
      this.spcPermissionsSyncGroupOperationsTotal.add(count, {
        sp_site_id: siteId.toString(),
        operation,
      });
    }

    return {
      updatedUniqueGroupsMap: pickBy(updatedUniqueGroupsMap, (group) => isNonNullish(group)),
    };
  }

  private async createUniqueGroup(
    siteId: Smeared,
    siteName: string,
    sharePointGroup: SharepointGroupWithMembers,
    uniqueUsersMap: UniqueUsersMap,
  ): Promise<UniqueGroupWithMembers | null> {
    const memberIds = getUniqueMemberIds(sharePointGroup, uniqueUsersMap);

    if (memberIds.length === 0) {
      return null;
    }

    const uniqueGroup = await this.uniqueGroupsService.createGroup({
      name: getUniqueGroupName(siteName, sharePointGroup.displayName),
      externalId: getSharepointConnectorGroupExternalId(siteId.value, sharePointGroup.id),
    });

    await this.uniqueGroupsService.addGroupMembers(uniqueGroup.id, memberIds);
    uniqueGroup.memberIds = memberIds;

    return uniqueGroup;
  }

  private async syncExistingUniqueGroup(
    uniqueGroup: UniqueGroupWithMembers,
    siteName: string,
    sharePointGroup: SharepointGroupWithMembers,
    uniqueUsersMap: UniqueUsersMap,
  ): Promise<[groupUpdated: boolean, UniqueGroupWithMembers | null]> {
    const memberIdsFromSharePoint = getUniqueMemberIds(sharePointGroup, uniqueUsersMap);

    // TODO: Uncomment this once https://unique-ch.atlassian.net/browse/UN-15272 is resolved.
    //       We've encountered a problem where scope accesses are not cleared correctly resulting in
    //       orphaned scope accesses that we could no longer delete due to access checks.
    // if (memberIdsFromSharePoint.length === 0) {
    //   await this.uniqueGroupsService.deleteGroup(uniqueGroup.id);
    //   return [true, null];
    // }

    let groupUpdated = false;

    // Currently nothing other than name is used in the Unique Groups so we keep check simple
    if (uniqueGroup.name !== getUniqueGroupName(siteName, sharePointGroup.displayName)) {
      const updatedUniqueGroup = await this.uniqueGroupsService.updateGroup({
        id: uniqueGroup.id,
        name: getUniqueGroupName(siteName, sharePointGroup.displayName),
      });
      uniqueGroup = { ...updatedUniqueGroup, memberIds: uniqueGroup.memberIds };
      groupUpdated = true;
    }

    const memberIdsToAdd = difference(memberIdsFromSharePoint, uniqueGroup.memberIds);
    const memberIdsToRemove = difference(uniqueGroup.memberIds, memberIdsFromSharePoint);

    if (memberIdsToAdd.length > 0) {
      await this.uniqueGroupsService.addGroupMembers(uniqueGroup.id, memberIdsToAdd);
      groupUpdated = true;
    }

    if (memberIdsToRemove.length > 0) {
      await this.uniqueGroupsService.removeGroupMembers(uniqueGroup.id, memberIdsToRemove);
      groupUpdated = true;
    }

    return [
      groupUpdated,
      {
        ...uniqueGroup,
        memberIds: memberIdsFromSharePoint,
      },
    ];
  }
}

function getUniqueGroupName(siteName: string, sharePointGroupName: string): string {
  return `[SPC-${siteName}] ${sharePointGroupName}`;
}

function getUniqueMemberIds(
  sharePointGroup: SharepointGroupWithMembers,
  uniqueUsersMap: UniqueUsersMap,
): string[] {
  return pipe(
    sharePointGroup.members,
    map((memberEmail) => uniqueUsersMap[memberEmail]),
    filter(isNonNullish),
  );
}
