import { GroupMembership, GroupUniqueId, MembershipType } from './types';

export const OWNERS_SUFFIX = '_o';

export const groupUniqueId = (group: Pick<GroupMembership, 'type' | 'id'>): GroupUniqueId =>
  `${group.type}:${group.id}`;

export const isGroupType = <T extends { type: MembershipType }>(
  item: T,
): item is T & { type: 'groupMembers' | 'groupOwners' } =>
  item.type === 'groupMembers' || item.type === 'groupOwners';
