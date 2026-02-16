// TODO: Check fi it's sensitive data.
export const getRootScopePath = (userIdentifier: string): string =>
  `/Outlook/${userIdentifier}/_to_process`;

export const getRootScopeExternalId = (userIdentifier: string): string =>
  `Outlook/${userIdentifier}/_to_process`;
