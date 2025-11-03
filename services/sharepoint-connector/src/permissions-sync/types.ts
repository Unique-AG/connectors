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

export type GroupUniqueId = `${Exclude<MembershipType, 'user'>}:${string}`;
