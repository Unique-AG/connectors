import assert from 'node:assert';
import { Injectable } from '@nestjs/common';
import {
  chunk,
  filter,
  flat,
  fromEntries,
  last,
  map,
  mapKeys,
  mapValues,
  partition,
  pick,
  pipe,
  prop,
  unique,
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
import type { GroupMembership, GroupUniqueId, Membership } from './types';
import { groupUniqueId, isGroupType, OWNERS_SUFFIX } from './utils';

interface GroupWithMembers {
  id: GroupUniqueId;
  displayName: string;
  members: string[]; // list of emails of the members
}

@Injectable()
export class FetchGroupsWithMembershipsQuery {
  public constructor(
    private readonly graphApiService: GraphApiService,
    private readonly sharepointRestClientService: SharepointRestClientService,
  ) {}

  public async run(
    siteId: string,
    permissions: Membership[],
  ): Promise<Record<string, GroupWithMembers>> {
    const siteWebUrl = await this.graphApiService.getSiteWebUrl(siteId);
    const siteName = siteWebUrl.split('/').pop();
    assert.ok(siteName, `Site name not found for site ${siteId}`);

    const siteGroupsPermissions = pipe(
      permissions,
      filter((permission) => permission.type === 'siteGroup'),
      uniqueBy(groupUniqueId),
    );

    const siteGroupIds = siteGroupsPermissions.map((permission) => permission.id);
    const groupMembershipsMap = await this.fetchSiteGroupsMembershipsMap(siteName, siteGroupIds);

    let msGroupsToProcess = pipe(
      [...permissions, ...pipe(groupMembershipsMap, values(), flat())],
      filter(isGroupType),
      uniqueBy(groupUniqueId),
      map(pick(['id', 'type'])),
    );

    while (msGroupsToProcess.length > 0) {
      const responseMappings = await this.fetchGroupMemberships(msGroupsToProcess);
      responseMappings.forEach(([groupId, itemPermissions]) => {
        groupMembershipsMap[groupId] = itemPermissions;
      });
      msGroupsToProcess = pipe(
        responseMappings,
        map(last()),
        flat(),
        filter(isGroupType),
        filter((group) => !groupMembershipsMap[groupUniqueId(group)]),
        uniqueBy(groupUniqueId),
        map(pick(['id', 'type'])),
      );
    }

    return pipe(
      permissions,
      filter((permission) => permission.type !== 'user'),
      uniqueBy(groupUniqueId),
      map<GroupMembership[], [GroupUniqueId, GroupWithMembers]>((group) => [
        groupUniqueId(group),
        this.mapItemPermissionToGroupWithMembers(group, groupMembershipsMap),
      ]),
      fromEntries(),
      // We need type forcing because GroupUniqueId type forces weird result on
      // fromEntries - GroupWithMembers | undefined instead of just GroupWithMembers.
    ) as Record<GroupUniqueId, GroupWithMembers>;
  }

  private mapItemPermissionToGroupWithMembers(
    group: GroupMembership,
    groupsMembershipsMap: Record<string, Membership[]>,
  ): GroupWithMembers {
    const groupId = groupUniqueId(group);
    const groupName = group.name;
    const groupMembers: string[] = [];

    let processedGroupIds: GroupUniqueId[] = [groupId];
    do {
      const newProcessedGroupIds: GroupUniqueId[] = [];
      for (const currentGroupId of processedGroupIds) {
        const [currentGroupUserMembers, currentGroupGroupMembers] = partition(
          groupsMembershipsMap[currentGroupId] ?? [],
          (membership) => membership.type === 'user',
        );
        groupMembers.push(...currentGroupUserMembers.map(prop('email')));
        newProcessedGroupIds.push(...currentGroupGroupMembers.map(groupUniqueId));
      }
      processedGroupIds = newProcessedGroupIds;
    } while (processedGroupIds.length > 0);

    return {
      id: groupId,
      displayName: groupName,
      members: unique(groupMembers),
    };
  }
  // ===== Helper methods for fetching groups from Microsoft Graph API =====

  private async fetchGroupMemberships(
    groups: { id: string; type: 'groupMembers' | 'groupOwners' }[],
  ): Promise<[GroupUniqueId, Membership[]][]> {
    // TODO: Once we have batch requests for Graph API implemented, change this method to take
    // advantage of that instead of chunking manually.

    const chunkedGroups = chunk(groups, 20);
    const groupMembershipsMappings: [GroupUniqueId, Membership[]][] = [];
    for (const groupChunk of chunkedGroups) {
      const groupMemberships = await Promise.all(
        groupChunk.map((group) =>
          group.type === 'groupMembers'
            ? this.graphApiService.getGroupMembers(group.id)
            : this.graphApiService.getGroupOwners(group.id),
        ),
      );
      const chunkIds = groupChunk.map(groupUniqueId);
      const chunkItemPermissions = groupMemberships.map(
        map(this.mapGroupMembershipToItemPermission.bind(this)),
      );
      groupMembershipsMappings.concat(zip(chunkIds, chunkItemPermissions));
    }
    return groupMembershipsMappings;
  }

  private mapGroupMembershipToItemPermission(membership: GroupMember): Membership {
    if (membership['@odata.type'] === '#microsoft.graph.user') {
      return {
        type: 'user',
        email:
          membership.mail ||
          membership.userPrincipalName ||
          assert.fail(`User has no email or userPrincipalName: ${JSON.stringify(membership)}`),
      };
    }

    return {
      type: 'groupMembers',
      id: membership.id,
      name: membership.displayName,
    };
  }

  // ===== Helper methods for fetching groups from SharePoint REST API =====

  private async fetchSiteGroupsMembershipsMap(
    siteName: string,
    siteGroupIds: string[],
  ): Promise<Record<GroupUniqueId, Membership[]>> {
    return pipe(
      await this.sharepointRestClientService.getSiteGroupsMemberships(siteName, siteGroupIds),
      mapKeys((id) => groupUniqueId({ type: 'siteGroup', id })),
      mapValues(map(this.mapRestApiMembershipToGroupMembership.bind(this))),
    );
  }

  private mapRestApiMembershipToGroupMembership({
    PrincipalType: principalType,
    LoginName: loginName,
    Email: email,
    Title: title,
  }: SiteGroupMembership): Membership {
    const principalTypeMapper: Record<PrincipalType, () => Membership> = {
      [PrincipalType.User]: () => ({ type: 'user', email }),
      [PrincipalType.DistributionList]: () => ({
        type: 'groupMembers',
        name: title,
        id: this.extractGroupId(loginName),
      }),
      [PrincipalType.SecurityGroup]: () => {
        const groupId = this.extractGroupId(loginName);
        return {
          type: `group${groupId.endsWith(OWNERS_SUFFIX) ? 'Owners' : 'Members'}`,
          id: groupId,
          name: title,
        };
      },
      [PrincipalType.SharePointGroup]: () =>
        assert.fail(`SharePoint site groups nesting is not supported in SharePoint`),
    };
    return principalTypeMapper[principalType]();
  }

  private extractGroupId(loginName: string): string {
    return (
      loginName.split('|').pop() ?? assert.fail(`Invalid login name for a group: ${loginName}`)
    );
  }
}
