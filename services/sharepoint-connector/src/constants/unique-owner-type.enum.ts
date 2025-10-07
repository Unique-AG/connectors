export const UniqueOwnerType = {
  Scope: 'SCOPE',
  Company: 'COMPANY',
  User: 'USER',
  Chat: 'CHAT',
} as const;

export type UniqueOwnerType = (typeof UniqueOwnerType)[keyof typeof UniqueOwnerType];
