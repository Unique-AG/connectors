export interface Group {
  id: string;
  name: string;
  externalId: string;
}

export interface GroupWithMembers extends Group {
  memberIds: string[];
}
