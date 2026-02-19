export const getRootScopePath = (userProviderIdentifier: string): string =>
  `/Outlook_${userProviderIdentifier}_uncategoried`;

export const getRootScopeExternalId = (userProviderIdentifier: string): string =>
  `Outlook_${userProviderIdentifier}_uncategoried`;
