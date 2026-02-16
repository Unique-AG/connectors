import type { Group, GroupWithMembers } from '../groups/groups.types';

export interface UniqueApiGroups {
  listByExternalIdPrefix(externalIdPrefix: string): Promise<GroupWithMembers[]>;
  create(group: { name: string; externalId: string; createdBy: string }): Promise<GroupWithMembers>;
  update(group: { id: string; name: string }): Promise<Group>;
  delete(groupId: string): Promise<void>;
  addMembers(groupId: string, memberIds: string[]): Promise<void>;
  removeMembers(groupId: string, userIds: string[]): Promise<void>;
}
