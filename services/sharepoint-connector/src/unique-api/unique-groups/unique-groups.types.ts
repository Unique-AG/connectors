export interface UniqueGroup {
  id: string;
  name: string;
  externalId: string;
}

export interface UniqueGroupWithMembers extends UniqueGroup {
  memberIds: string[];
}
