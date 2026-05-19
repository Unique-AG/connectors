import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, desc, eq, isNotNull } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, UserProfile, userProfiles } from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { NonNullishProps } from '~/utils/non-nullish-props';

export class NoDelegatesFoundError extends Error {
  public constructor(ownerUserId: string) {
    super(`No delegates found for owner: ${ownerUserId}`);
    this.name = 'NoDelegatesFoundError';
  }
}

export class AllDelegatesFailedError extends Error {
  public constructor(ownerUserId: string) {
    super(`All delegates exhausted with 403 for owner: ${ownerUserId}`);
    this.name = 'AllDelegatesFailedError';
  }
}

@Injectable()
export class MsGraphClientResolver {
  private readonly logger = new Logger(MsGraphClientResolver.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  /**
   * Resolves a Graph client for `userProfile` and calls `fn` with it.
   *
   * - **oauth profiles** — creates a client directly for the user's own token; `fn` is called once.
   * - **shared-mailbox profiles** — queries `delegatedAccessAccounts` for delegates ordered by
   *   `lastVerifiedAt DESC`, then tries each in turn (up to `maxRetries`, default 3). A 403 from
   *   Graph moves to the next candidate; any other error is rethrown immediately. If all candidates
   *   exhaust with 403, `AllDelegatesFailedError` is thrown.
   *
   * The `userProfile` passed to `fn` is always the **owner** (the mailbox being operated on), not
   * the delegate. Graph paths should use `userProfile.email` (e.g. `users/${userProfile.email}/…`).
   *
   * Return type depends on `throwIfNoDelegates`:
   * - omitted / `false` → returns `null` when no delegates exist (shared-mailbox only)
   * - `true`            → throws `NoDelegatesFoundError` instead; return type narrows to `T`
   *
   * @example
   * // Basic usage — skip silently when no delegates are available
   * const result = await this.msGraphClientResolver.run({
   *   userProfile,
   *   fn: ({ client, userProfile }) => fetchSomething(client, userProfile.email),
   * });
   * if (result === null) return; // shared-mailbox with no delegates yet
   *
   * @example
   * // Require a delegate — throw if none found
   * const result = await this.msGraphClientResolver.run({
   *   userProfile,
   *   fn: ({ client, userProfile }) => fetchSomething(client, userProfile.email),
   *   sharedMailboxConfig: { throwIfNoDelegates: true },
   * });
   */
  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: { client: Client; userProfile: NonNullishProps<UserProfile, 'email'> }) => Promise<T>;
    sharedMailboxConfig: { throwIfNoDelegates: true; maxRetries?: number };
  }): Promise<T>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: { client: Client; userProfile: NonNullishProps<UserProfile, 'email'> }) => Promise<T>;
    sharedMailboxConfig?: { throwIfNoDelegates?: false; maxRetries?: number };
  }): Promise<T | null>;

  // Covers callers that pass a runtime boolean variable for throwIfNoDelegates.
  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: { client: Client; userProfile: NonNullishProps<UserProfile, 'email'> }) => Promise<T>;
    sharedMailboxConfig?: { throwIfNoDelegates?: boolean; maxRetries?: number };
  }): Promise<T | null>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: { client: Client; userProfile: NonNullishProps<UserProfile, 'email'> }) => Promise<T>;
    sharedMailboxConfig?: { throwIfNoDelegates?: boolean; maxRetries?: number };
  }): Promise<T | null> {
    const { userProfile, fn, sharedMailboxConfig } = input;
    const maxRetries = sharedMailboxConfig?.maxRetries ?? 3;
    const throwIfNoDelegates = sharedMailboxConfig?.throwIfNoDelegates ?? false;

    if (userProfile.source === 'oauth') {
      const client = this.graphClientFactory.createClientForUser(userProfile.id);
      return fn({ client, userProfile });
    }

    // source === 'shared-mailbox': use delegated access
    const delegates = await this.db
      .select({ delegateUserId: delegatedAccessAccounts.delegateUserId })
      .from(delegatedAccessAccounts)
      .innerJoin(
        userProfiles,
        and(
          eq(userProfiles.id, delegatedAccessAccounts.delegateUserId),
          eq(userProfiles.source, 'oauth'),
          isNotNull(userProfiles.accessToken),
        ),
      )
      .where(eq(delegatedAccessAccounts.ownerUserId, userProfile.id))
      .orderBy(desc(delegatedAccessAccounts.lastVerifiedAt));

    if (delegates.length === 0) {
      if (throwIfNoDelegates) {
        throw new NoDelegatesFoundError(userProfile.id);
      }
      return null;
    }

    const candidates = delegates.slice(0, maxRetries);

    for (const delegate of candidates) {
      const client = this.graphClientFactory.createClientForUser(delegate.delegateUserId);
      try {
        return await fn({ client, userProfile });
      } catch (error) {
        if (error instanceof GraphError && (error.statusCode === 401 || error.statusCode === 403)) {
          continue;
        }
        throw error;
      }
    }

    this.logger.warn({ ownerUserId: userProfile.id, msg: 'All delegates exhausted with 403' });
    throw new AllDelegatesFailedError(userProfile.id);
  }
}
