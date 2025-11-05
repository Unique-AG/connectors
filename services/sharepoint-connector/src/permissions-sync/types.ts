// TODO: Consider using name Access instead of Membership or Permission. It encompasses both
//       permissions on files/folders and memberships of groups.

import { UniqueGroup } from '../unique-api/unique-groups/unique-groups.types';

export type UserMembership = {
  type: 'user';
  email: string;
};

export type GroupMembership =
  | {
      type: 'siteGroup';
      id: string;
      name: string;
    }
  | {
      type: 'groupMembers';
      id: string;
      name: string;
    }
  | {
      type: 'groupOwners';
      id: string;
      name: string;
    };

export type Membership = UserMembership | GroupMembership;

export type MembershipType = Membership['type'];

export type GroupDistinctId = `${Exclude<MembershipType, 'user'>}:${string}`;

export interface SharepointGroupWithMembers {
  id: GroupDistinctId;
  displayName: string;
  members: string[]; // list of emails of the members
}

export type SharePointGroupsMap = Record<GroupDistinctId, SharepointGroupWithMembers>;
export type UniqueGroupsMap = Record<GroupDistinctId, UniqueGroup>;
export type UniqueUsersMap = Record<string, string>; // email -> unique user id
