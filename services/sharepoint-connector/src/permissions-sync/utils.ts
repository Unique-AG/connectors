import { GroupDistinctId, GroupMembership, MembershipType } from './types';

export const OWNERS_SUFFIX = '_o';
export const ALL_USERS_GROUP_ID_PREFIX = 'spo-grid-all-users/';

export const groupDistinctId = (group: Pick<GroupMembership, 'type' | 'id'>): GroupDistinctId =>
  `${group.type}:${group.id}`;

export const isGroupType = <T extends { type: MembershipType }>(
  item: T,
): item is T & { type: 'groupMembers' | 'groupOwners' } =>
  item.type === 'groupMembers' || item.type === 'groupOwners';

export function normalizeMsGroupId(groupId: string): string {
  return groupId.replace(new RegExp(`${OWNERS_SUFFIX}$`), '');
}
