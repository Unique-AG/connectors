export type ItemPermission =
  | {
      type: 'user';
      id: string;
      email: string;
    }
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
