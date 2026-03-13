export interface UniqueIdentity {
  userId: string;
  companyId: string;
}

export interface UserIdentityResolver {
  /**
   * Resolves an application-specific user identifier to a Unique platform identity.
   * The implementation is responsible for caching, DB lookups, etc.
   */
  resolve(userIdentifier: string): Promise<UniqueIdentity>;
}
