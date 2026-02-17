// TODO: Check fi it's sensitive data.
export const getRootScopePath = (userIdentifier: string): string =>
  `/Outlook_${userIdentifier}_uncategoried`;

// TODO: Adjust
export const getRootScopeExternalId = (userIdentifier: string): string =>
  `Outlook_${userIdentifier}_uncategoried`;
