// TODO: Check fi it's sensitive data.
export const getRootScopePath = (userEmail: string): string => `Outlook/${userEmail}/_to_process`;
