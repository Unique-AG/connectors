import assert from 'assert';
import { Injectable, Logger } from '@nestjs/common';
import { difference, filter, isNonNullish, keys, map, pickBy, pipe } from 'remeda';
import { SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX } from '../unique-api/unique-groups/unique-groups.consts';
import { UniqueGroupsService } from '../unique-api/unique-groups/unique-groups.service';
import { UniqueGroup } from '../unique-api/unique-groups/unique-groups.types';
import {
  GroupDistinctId,
  SharePointGroupsMap,
  SharepointGroupWithMembers,
  UniqueGroupsMap,
  UniqueUsersMap,
} from './types';

const SHAREPOINT_GROUP_NAME_PREFIX = '[SPC]';

interface Input {
  sharePointGroupsMap: SharePointGroupsMap;
  uniqueGroupsMap: UniqueGroupsMap;
  uniqueUsersMap: UniqueUsersMap;
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

  public constructor(private readonly uniqueGroupsService: UniqueGroupsService) {}

  public async run(input: Input): Promise<Output> {
    const { sharePointGroupsMap, uniqueGroupsMap, uniqueUsersMap } = input;
    const updatedUniqueGroupsMap: Record<GroupDistinctId, UniqueGroup | null> = {};

    const sharePointGroups = Object.values(sharePointGroupsMap);
    this.logger.log(`Syncing ${sharePointGroups.length} sharepoint groups`);
    const groupsSyncStats: { created: number; updated: number; deleted: number; skipped: number } =
      {
        created: 0,
        updated: 0,
        deleted: 0,
        skipped: 0,
      };

    for (const sharePointGroup of sharePointGroups) {
      const logPrefix = `[Group: ${sharePointGroup.id}]`;
      this.logger.debug(`${logPrefix} Syncing sharepoint group ${sharePointGroup.displayName}`);

      const correspondingUniqueGroup = uniqueGroupsMap[sharePointGroup.id];
      if (!correspondingUniqueGroup) {
        const newUniqueGroup = await this.createUniqueGroup(sharePointGroup, uniqueUsersMap);
        updatedUniqueGroupsMap[sharePointGroup.id] = newUniqueGroup;
        if (newUniqueGroup) {
          groupsSyncStats.created++;
          this.logger.debug(`${logPrefix} Created new Unique Group`);
        } else {
          groupsSyncStats.skipped++;
          this.logger.debug(`${logPrefix} Skipped Unique Group creation due to no members`);
        }
        continue;
      }

      const [didUpdate, updatedUniqueGroup] = await this.syncExistingUniqueGroup(
        correspondingUniqueGroup,
        sharePointGroup,
        uniqueUsersMap,
      );
      if (didUpdate) {
        updatedUniqueGroupsMap[sharePointGroup.id] = updatedUniqueGroup;
        if (updatedUniqueGroup) {
          groupsSyncStats.updated++;
          this.logger.debug(`${logPrefix} Updated Unique Group`);
        } else {
          groupsSyncStats.deleted++;
          this.logger.debug(`${logPrefix} Deleted Unique Group due to no members`);
        }
        continue;
      }

      this.logger.debug(`${logPrefix} No changes to Unique Group`);
      updatedUniqueGroupsMap[sharePointGroup.id] = correspondingUniqueGroup;
    }

    const missingGroupDistinctIds = difference(keys(uniqueGroupsMap), keys(updatedUniqueGroupsMap));

    this.logger.log(`Deleting ${missingGroupDistinctIds.length} missing unique groups`);
    for (const groupDistinctId of missingGroupDistinctIds) {
      const missingGroup =
        uniqueGroupsMap[groupDistinctId] ??
        assert.fail(`Missing group ${groupDistinctId} in unique groups map`);
      await this.uniqueGroupsService.deleteGroup(missingGroup.id);
      groupsSyncStats.deleted++;
    }

    this.logger.log(
      `Synced ${sharePointGroups.length} sharepoint groups:\n` +
        `    Created: ${groupsSyncStats.created} groups\n` +
        `    Updated: ${groupsSyncStats.updated} groups\n` +
        `    Deleted: ${groupsSyncStats.deleted} groups\n` +
        `    Skipped: ${groupsSyncStats.skipped} groups`,
    );

    return {
      updatedUniqueGroupsMap: pickBy(updatedUniqueGroupsMap, (group) => isNonNullish(group)),
    };
  }

  private async createUniqueGroup(
    sharePointGroup: SharepointGroupWithMembers,
    uniqueUsersMap: UniqueUsersMap,
  ): Promise<UniqueGroup | null> {
    const memberIds = getUniqueMemberIds(sharePointGroup, uniqueUsersMap);

    if (memberIds.length === 0) {
      return null;
    }

    const uniqueGroup = await this.uniqueGroupsService.createGroup({
      name: getUniqueGroupName(sharePointGroup.displayName),
      externalId: `${SHAREPOINT_CONNECTOR_GROUP_EXTERNAL_ID_PREFIX}${sharePointGroup.id}`,
    });

    await this.uniqueGroupsService.addGroupMembers(uniqueGroup.id, memberIds);
    uniqueGroup.memberIds = memberIds;

    return uniqueGroup;
  }

  private async syncExistingUniqueGroup(
    uniqueGroup: UniqueGroup,
    sharePointGroup: SharepointGroupWithMembers,
    uniqueUsersMap: UniqueUsersMap,
  ): Promise<[groupUpdated: boolean, UniqueGroup | null]> {
    const memberIdsFromSharePoint = getUniqueMemberIds(sharePointGroup, uniqueUsersMap);

    if (memberIdsFromSharePoint.length === 0) {
      await this.uniqueGroupsService.deleteGroup(uniqueGroup.id);
      return [true, null];
    }

    let groupUpdated = false;

    // Currently nothing other than name is used in the Unique Groups so we keep check simple
    if (uniqueGroup.name !== getUniqueGroupName(sharePointGroup.displayName)) {
      const updatedUniqueGroup = await this.uniqueGroupsService.updateGroup({
        id: uniqueGroup.id,
        name: getUniqueGroupName(sharePointGroup.displayName),
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

function getUniqueGroupName(sharePointGroupName: string): string {
  return `${SHAREPOINT_GROUP_NAME_PREFIX} ${sharePointGroupName}`;
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
