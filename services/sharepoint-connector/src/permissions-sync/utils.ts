import { normalizeSlashes } from '../utils/paths.util';
import { Smeared } from '../utils/smeared';
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

// Determines if a path is a site/subsite root or first library level.
// Top folders use aggregated descendant group permissions.
// Deeper descendants are regular folders and return false.
export function isTopFolder(
  path: Smeared,
  rootPath: Smeared,
  subsiteRelativePaths: string[] = [],
): boolean {
  if (path.value === rootPath.value) {
    return true;
  }

  const relativePart = normalizeSlashes(
    path.value.replace(`/${normalizeSlashes(rootPath.value)}/`, ''),
  );

  // If the path has no slashes, it means it's either subsite folder or library folder in the top
  // site, which are both top folders.
  if (!relativePart.includes('/')) {
    return true;
  }

  for (const subsitePath of subsiteRelativePaths) {
    // Subsite folders are top folders.
    if (relativePart === subsitePath) {
      return true;
    }

    // If the path doesn't start with subsitePrefix, it's surely not a top folder in this subsite.
    const subsitePrefix = `${subsitePath}/`;
    if (!relativePart.startsWith(subsitePrefix)) {
      continue;
    }

    const belowSubsite = relativePart.slice(subsitePrefix.length);
    // If it has no slashes, it means there is only one segment, which at this point means it's
    // either SitePages or Drive folder, which are both top folders.
    if (!belowSubsite.includes('/')) {
      return true;
    }
  }

  return false;
}
