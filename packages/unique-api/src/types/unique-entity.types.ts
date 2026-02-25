export type UniqueEntityType = 'GROUP' | 'USER';

export type UniqueAccessType = 'MANAGE' | 'READ' | 'WRITE';

export const UniqueOwnerType = {
  Scope: 'SCOPE',
  Company: 'COMPANY',
  User: 'USER',
  Chat: 'CHAT',
} as const;

export type UniqueOwnerType = (typeof UniqueOwnerType)[keyof typeof UniqueOwnerType];
