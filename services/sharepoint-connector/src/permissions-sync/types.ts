// TODO: Consider using name Access instead of Membership or Permission. It encompasses both
//       permissions on files/folders and memberships of groups.

import { UniqueGroupWithMembers } from '../unique-api/unique-groups/unique-groups.types';
import type { Smeared } from '../utils/smeared';

export interface UserMembership {
  type: 'user';
  email: string;
}

export type GroupMembership =
  | {
      siteId: Smeared;
      type: 'siteGroup';
      id: string;
      name: string;
    }
  | {
      siteId: Smeared;
      type: 'groupMembers';
      id: string;
      name: string;
    }
  | {
      siteId: Smeared;
      type: 'groupOwners';
      id: string;
      name: string;
    };

export type Membership = UserMembership | GroupMembership;

export type MembershipType = Membership['type'];

export type GroupDistinctId = `${Exclude<MembershipType, 'user'>}:${string}`;

export interface SharepointGroupWithMembers {
  id: GroupDistinctId;
  siteId: Smeared;
  displayName: string;
  members: string[]; // list of emails of the members
}

export type SharePointGroupsMap = Record<GroupDistinctId, SharepointGroupWithMembers>;
export type UniqueGroupsMap = Record<GroupDistinctId, UniqueGroupWithMembers>;
export type UniqueUsersMap = Record<string, string>; // email -> unique user id
