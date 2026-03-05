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

// Determines if a path is a "top folder" (site/subsite root or library level).
// Top folders use aggregated group permissions from their descendants instead of direct
// SharePoint permissions.
//
// For the main site:
//   /RootScope              -> true  (site root)
//   /RootScope/Drive        -> true  (library level, 1 segment)
//   /RootScope/Drive/Folder -> false (regular folder)
//
// For subsites (e.g. subsiteRelativePaths = ["SubSite"]):
//   /RootScope/SubSite              -> true  (subsite root, 1 segment but matches subsite)
//   /RootScope/SubSite/Drive        -> true  (subsite library level)
//   /RootScope/SubSite/Drive/Folder -> false (regular folder)
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
