// TODO: Clean up the naming - Permission vs Membership
//       It is used in different places with different meanings and question is whether we define
//       two with the same stucture or simply explain that we return onr in the other situation
//       because it's the same structure.

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

export type ItemPermission = UserMembership | GroupMembership;

export type PermissionType = ItemPermission['type'];

export type GroupUniqueId = `${Exclude<PermissionType, 'user'>}:${string}`;

export const groupUniqueId = (group: Pick<GroupMembership, 'type' | 'id'>): GroupUniqueId =>
  `${group.type}:${group.id}`;
