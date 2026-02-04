import { normalizeSlashes } from '../utils/paths.util';
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

// Determines if a path is a "top folder" (site or library level).
// Top folders use aggregated group permissions from their descendants instead of direct
// SharePoint permissions.
// Example: /RootScope/Drive/Folder -> Drive/Folder -> 2 levels -> false (regular folder)
// Example: /RootScope/Drive -> Drive -> 1 level -> true (library)
// Example: /RootScope -> true (site)
export function isTopFolder(path: string, rootPath: string): boolean {
  // The actual root path will not have replacement working for them because of no trailing slash,
  // so we handle it separately.
  if (path === rootPath) {
    return true;
  }
  // We're removing the root scope part, in case it has any slashes, to make it predictable. Then we
  // check if the remaining part has at most 1 level, because it indicates it is the drive level.
  return path.replace(`/${normalizeSlashes(rootPath)}/`, '').split('/').length <= 1;
}
