import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import {
  chunk,
  filter,
  flat,
  fromEntries,
  isNonNullish,
  last,
  length,
  map,
  mapKeys,
  mapValues,
  partition,
  pick,
  pipe,
  sum,
  uniqueBy,
  values,
  zip,
} from 'remeda';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { GroupMember } from '../microsoft-apis/graph/types/sharepoint.types';
import {
  PrincipalType,
  SharepointRestClientService,
  SiteGroupMembership,
} from '../microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { sanitizeError } from '../utils/normalize-error';
import { createSmeared, type Smeared } from '../utils/smeared';
import type {
  GroupDistinctId,
  GroupMembership,
  Membership,
  SharePointGroupsMap,
  SharepointGroupWithMembers,
} from './types';
import {
  ALL_USERS_GROUP_ID_PREFIX,
  groupDistinctId,
  isGroupType,
  normalizeMsGroupId,
  OWNERS_SUFFIX,
} from './utils';

@Injectable()
export class FetchGroupsWithMembershipsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly sharepointRestClientService: SharepointRestClientService,
  ) {}

  // For given list of group permissions from files/lists, fetch all the present sharepoint group
  // members from SharePoint and Graph APIs. Result is a map from GroupDistinctId to
  // SharepointGroupWithMembers.
  // Stages of this process are as follows:
  // 1. Fetch all the site groups from SharePoint REST API and add them to the cache. One call is
  //    enough because we know that SharePoint site groups are not nested.
  // 2. Fetch all the group members and owners from Graph API and add them to the cache. Here we
  //    have to query Graph API as long as we see groups that we've not encountered yet, because
  //    Security Groups can be nested.
  // 3. Go through group permissions passed to the service and map them to
  //    SharepointGroupWithMembers using the built cache of group memberships.
  public async run(
    siteId: Smeared,
    groupPermissions: GroupMembership[],
  ): Promise<SharePointGroupsMap> {
    const logPrefix = `[Site: ${siteId}]`;
    const uniqueGroupPermissions = uniqueBy(groupPermissions, groupDistinctId);

    this.logger.log(
      `${logPrefix} Fetching groups with memberships for ${uniqueGroupPermissions.length} unique ` +
        `group permissions`,
    );

    const siteGroupsPermissions = pipe(
      uniqueGroupPermissions,
      filter((permission) => permission.type === 'siteGroup'),
    );

    const groupMembershipsCache = await this.processSiteGroupsPermissions(
      siteGroupsPermissions,
      logPrefix,
    );
    const allMembershipsFromSiteGroups = pipe(groupMembershipsCache, values(), flat());
    let msGroupsToProcess = pipe(
      [...uniqueGroupPermissions, ...allMembershipsFromSiteGroups],
      filter(isGroupType),
      uniqueBy(groupDistinctId),
      map(pick(['id', 'type', 'siteId'])),
    );

    this.logger.log(`${logPrefix} Fetching MS groups memberships map`);
    while (msGroupsToProcess.length > 0) {
      this.logger.debug(
        `${logPrefix} Fetching MS groups memberships for ${msGroupsToProcess.length} groups`,
      );
      const responseMappings = await this.fetchGroupMemberships(msGroupsToProcess, logPrefix);
      responseMappings.forEach(([groupId, itemPermissions]) => {
        groupMembershipsCache[groupId] = itemPermissions;
      });
      msGroupsToProcess = pipe(
        responseMappings,
        map(last()),
        flat(),
        filter(isGroupType),
        filter((group) => !groupMembershipsCache[groupDistinctId(group)]),
        uniqueBy(groupDistinctId),
        map(pick(['id', 'type', 'siteId'])),
      );
      this.logger.debug(`${logPrefix} Found ${msGroupsToProcess.length} groups to process next`);
    }

    const fetchedGroupsTotal = Object.keys(groupMembershipsCache).length;
    const fetchedMembershipsTotal = pipe(
      groupMembershipsCache,
      mapValues(length()),
      values(),
      sum(),
    );
    this.logger.log(
      `${logPrefix} Done fetching MS groups memberships. Fetched ${fetchedGroupsTotal} groups ` +
        `with total ${fetchedMembershipsTotal} memberships`,
    );

    return pipe(
      uniqueGroupPermissions,
      map<GroupMembership[], [GroupDistinctId, SharepointGroupWithMembers]>((group) => [
        groupDistinctId(group),
        this.mapItemPermissionToGroupWithMembers(group, groupMembershipsCache),
      ]),
      fromEntries(),
      // We need type forcing because GroupDistinctId type forces weird result on fromEntries.
      // It's SharepointGroupWithMembers | undefined instead of just SharepointGroupWithMembers.
    ) as SharePointGroupsMap;
  }

  private mapItemPermissionToGroupWithMembers(
    group: GroupMembership,
    groupsMembershipsCache: Record<GroupDistinctId, Membership[]>,
  ): SharepointGroupWithMembers {
    const groupId = groupDistinctId(group);
    const groupName = group.name;
    const groupMembers: Set<string> = new Set();

    // We need to track encountered group ids to avoid infinite loops due to circular dependencies.
    const encounteredGroupIds = new Set<GroupDistinctId>();
    let groupIdsToProcess: GroupDistinctId[] = [groupId];
    // We may have to to process groups multiple times because Entra groups (AFAIK only Security
    // Groups) can be nested.
    do {
      const groupIdsToProcessNext: GroupDistinctId[] = [];
      for (const currentGroupId of groupIdsToProcess) {
        // This check is necessary to avoid infinite loops due to circular dependencies.
        if (encounteredGroupIds.has(currentGroupId)) {
          continue;
        }
        const [currentGroupUserMembers, currentGroupGroupMembers] = partition(
          groupsMembershipsCache[currentGroupId] ?? [],
          (membership) => membership.type === 'user',
        );
        currentGroupUserMembers.forEach((userMembership) => {
          groupMembers.add(userMembership.email);
        });
        groupIdsToProcessNext.push(...currentGroupGroupMembers.map(groupDistinctId));
        encounteredGroupIds.add(currentGroupId);
      }
      groupIdsToProcess = groupIdsToProcessNext;
    } while (groupIdsToProcess.length > 0);

    return {
      id: groupId,
      siteId: group.siteId,
      displayName: groupName,
      members: Array.from(groupMembers),
    };
  }
  // ===== Helper methods for fetching groups from Microsoft Graph API =====

  private async fetchGroupMemberships(
    groups: { id: string; siteId: Smeared; type: 'groupMembers' | 'groupOwners' }[],
    logPrefix: string,
  ): Promise<[GroupDistinctId, Membership[]][]> {
    // This can use Graph API batch requests once batching support is implemented.

    const chunkedGroups = chunk(groups, 20);
    const groupMembershipsMappings: [GroupDistinctId, Membership[]][] = [];
    for (const groupChunk of chunkedGroups) {
      // We use Promise.allSettled instead of Promise.all to gracefully handle deleted groups.
      // When an Entra group is deleted, SharePoint may still reference it in permissions, but
      // Graph API returns 404 when trying to fetch members. We treat such groups as having
      // empty memberships while still throwing on other types of errors.
      const groupMembershipsResults = await Promise.allSettled(
        groupChunk.map((group) =>
          group.type === 'groupOwners'
            ? this.graphApiService.getGroupOwners(group.id)
            : this.graphApiService.getGroupMembers(group.id),
        ),
      );

      const chunkIds = groupChunk.map(groupDistinctId);
      const chunkItemPermissions = groupMembershipsResults.map((result, index) => {
        const group = groupChunk[index];
        assert.ok(group, `Missing group at index ${index} in chunk`);

        if (result.status === 'fulfilled') {
          return result.value.map((membership) =>
            this.mapGroupMembershipToItemPermission(membership, group.siteId),
          );
        }

        // References to deleted Entra groups still appear in SharePoint REST API permissions but
        // return 404 from Graph API when we request memberships.
        // We check for 404 status to identify these cases and treat them as empty memberships.
        const error = result.reason as Error & { statusCode?: number };

        if (error.statusCode === 404) {
          this.logger.warn(
            `Group ${createSmeared(group.id)} not found (404) - likely deleted from Entra ID but still ` +
              `referenced in SharePoint permissions. Treating as empty membership.`,
          );
          return [];
        }

        this.logger.error({
          msg: `${logPrefix} Failed to fetch memberships for group`,
          groupId: createSmeared(group.id),
          error: sanitizeError(error),
        });
        throw error;
      });
      groupMembershipsMappings.push(...zip(chunkIds, chunkItemPermissions));
    }
    return groupMembershipsMappings;
  }

  private mapGroupMembershipToItemPermission(membership: GroupMember, siteId: Smeared): Membership {
    if (membership['@odata.type'] === '#microsoft.graph.user') {
      return {
        type: 'user',
        email:
          membership.mail ||
          membership.userPrincipalName ||
          assert.fail(`User has no email or userPrincipalName`),
      };
    }

    return {
      siteId,
      type: 'groupMembers',
      id: membership.id,
      name: membership.displayName,
    };
  }

  // ===== Helper methods for fetching groups from SharePoint REST API =====

  private async processSiteGroupsPermissions(
    siteGroupsPermissions: GroupMembership[],
    logPrefix: string,
  ): Promise<Record<GroupDistinctId, Membership[]>> {
    const siteWithGroupIdsBySiteId: Record<
      string,
      { siteId: Smeared; siteName: string; siteGroupIds: string[] }
    > = {};
    for (const siteGroupPermission of siteGroupsPermissions) {
      const [siteName, siteGroupId, ...rest] = siteGroupPermission.id.split('|');

      // Validate the format of the site group id. It should be in the format of
      // "siteName|siteGroupId" but we are paranoid and want to check for extra parts just in case.
      const hasValidFormat = Boolean(siteName) && Boolean(siteGroupId) && rest.length === 0;
      if (!hasValidFormat) {
        this.logger.warn(
          `${logPrefix} Skipping site group with invalid id format: ${createSmeared(siteGroupPermission.id)}`,
        );
        continue;
      }

      assert.ok(siteName, 'Site name must be present');
      assert.ok(siteGroupId, 'Site group id must be present');
      const rawSiteId = siteGroupPermission.siteId.value;
      siteWithGroupIdsBySiteId[rawSiteId] ??= {
        siteId: createSmeared(rawSiteId),
        siteName,
        siteGroupIds: [],
      };
      siteWithGroupIdsBySiteId[rawSiteId].siteGroupIds.push(siteGroupId);
    }

    const totalSites = Object.keys(siteWithGroupIdsBySiteId).length;
    const totalSiteGroups = pipe(
      siteWithGroupIdsBySiteId,
      values(),
      map((site) => site.siteGroupIds.length),
      sum(),
    );
    this.logger.log(
      `${logPrefix} Fetching site groups memberships map for ${totalSiteGroups} site groups` +
        `${totalSites > 1 ? ` across ${totalSites} sites` : ''}`,
    );

    const aggregatedSiteGroupsMembershipsMap: Record<GroupDistinctId, Membership[]> = {};
    for (const { siteId, siteName, siteGroupIds } of Object.values(siteWithGroupIdsBySiteId)) {
      const siteGroupsMembershipsMapForSite = await this.fetchSiteGroupsMembershipsMap(
        createSmeared(siteName),
        siteGroupIds,
        siteId,
      );
      Object.assign(aggregatedSiteGroupsMembershipsMap, siteGroupsMembershipsMapForSite);
    }

    this.logger.log(`${logPrefix} Site groups memberships map fetched successfully`);
    return aggregatedSiteGroupsMembershipsMap;
  }

  private async fetchSiteGroupsMembershipsMap(
    siteName: Smeared,
    siteGroupIds: string[],
    siteId: Smeared,
  ): Promise<Record<GroupDistinctId, Membership[]>> {
    return pipe(
      await this.sharepointRestClientService.getSiteGroupsMemberships(siteName, siteGroupIds),
      // We need to add site name to the id to make it unique across all sites.
      mapKeys((id) =>
        groupDistinctId({
          type: 'siteGroup',
          id: `${siteName.value}|${id}`,
        }),
      ),
      mapValues(
        map((membership: SiteGroupMembership) =>
          this.mapRestApiMembershipToGroupMembership(membership, siteId),
        ),
      ),
      mapValues(filter(isNonNullish)),
    );
  }

  private mapRestApiMembershipToGroupMembership(
    siteGroupMembership: SiteGroupMembership,
    siteId: Smeared,
  ): Membership | null {
    const {
      PrincipalType: principalType,
      LoginName: loginName,
      Email: email,
      Title: title,
    } = siteGroupMembership;
    const principalTypeMapper: Record<PrincipalType, () => Membership | null> = {
      [PrincipalType.User]: () => {
        // In some specific cases, that are rather unclear, there may be no email specified in the
        // SharePoint REST API response, but it may be present in loginName field which looks like
        // "i:0#.f|membership|user@dogfood.industries".
        const userEmail = email || loginName.split('|').pop() || '';
        // Ensure the value resembles an email and we did not get something else, like
        // "SHAREPOINT\\system", from loginName split.
        return userEmail.includes('@') ? { type: 'user', email: userEmail } : null;
      },
      [PrincipalType.DistributionList]: () => {
        const groupId = this.extractGroupId(loginName);
        return groupId ? { siteId, type: 'groupMembers', id: groupId, name: title } : null;
      },
      [PrincipalType.SecurityGroup]: () => {
        const groupId = this.extractGroupId(loginName);
        // We skip "Everyone except external users" group because we wuld rather err on the side of
        // caution and not include any wildcard groups.
        if (groupId?.startsWith(ALL_USERS_GROUP_ID_PREFIX)) {
          return null;
        }
        const groupType = groupId?.endsWith(OWNERS_SUFFIX) ? 'Owners' : 'Members';
        return groupId
          ? { siteId, type: `group${groupType}`, id: normalizeMsGroupId(groupId), name: title }
          : null;
      },
      [PrincipalType.SharePointGroup]: () =>
        assert.fail(`SharePoint site groups nesting is not supported in SharePoint`),
    };
    return principalTypeMapper[principalType]();
  }

  private extractGroupId(loginName: string): string | null {
    return loginName.split('|').pop() ?? null;
  }
}
