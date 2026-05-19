import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, desc, eq, isNotNull } from 'drizzle-orm';
import { swapIndices } from 'remeda';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, UserProfile, userProfiles } from '~/db';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { NonNullishProps } from '~/utils/non-nullish-props';

export const NO_DELEGATES = Symbol('NO_DELEGATES');
export function isNoDelegatesResult(value: unknown): value is typeof NO_DELEGATES {
  return value === NO_DELEGATES;
}

export class NoDelegatesFoundError extends Error {
  public constructor(ownerUserId: string) {
    super(`No delegates found for owner: ${ownerUserId}`);
    this.name = 'NoDelegatesFoundError';
  }
}

export class AllDelegatesFailedError extends Error {
  public constructor(ownerUserId: string) {
    super(`All delegates exhausted (401/403) for owner: ${ownerUserId}`);
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
   *   `lastVerifiedAt DESC`, then tries each in turn (up to `maxDelegates`, default 3). A 401/403
   *   from Graph moves to the next candidate; any other error is rethrown immediately. If all
   *   candidates exhaust with 401/403, `AllDelegatesFailedError` is thrown.
   *
   * Graph paths inside `fn` should use the `userProfile` from the outer scope
   * (e.g. `users/${userProfile.email}/…`).
   *
   * Return type depends on `throwIfNoDelegates`:
   * - omitted / `false` → returns `NO_DELEGATES` symbol when no delegates exist (shared-mailbox only); use `isNoDelegates()` to check
   * - `true`            → throws `NoDelegatesFoundError` instead; return type narrows to `T`
   *
   * @example
   * // Basic usage — skip silently when no delegates are available
   * const result = await this.msGraphClientResolver.run({
   *   userProfile,
   *   fn: ({ client }) => fetchSomething(client, userProfile.email),
   * });
   * if (isNoDelegates(result)) return; // shared-mailbox with no delegates yet
   *
   * @example
   * // Require a delegate — throw if none found
   * const result = await this.msGraphClientResolver.run({
   *   userProfile,
   *   fn: ({ client }) => fetchSomething(client, userProfile.email),
   *   sharedMailboxConfig: { throwIfNoDelegates: true },
   * });
   */
  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: {
      client: Client;
      /** The user profile ID the client is authenticated as.
       * For `oauth` profiles this equals `userProfile.id`.
       * For `shared-mailbox` profiles this is the delegated OAuth user that was selected. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig: {
      throwIfNoDelegates: true;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
    };
  }): Promise<T>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: {
      client: Client;
      /** The user profile ID the client is authenticated as.
       * For `oauth` profiles this equals `userProfile.id`.
       * For `shared-mailbox` profiles this is the delegated OAuth user that was selected. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig?: {
      throwIfNoDelegates?: false;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
    };
  }): Promise<T | typeof NO_DELEGATES>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: {
      client: Client;
      /** The user profile ID the client is authenticated as.
       * For `oauth` profiles this equals `userProfile.id`.
       * For `shared-mailbox` profiles this is the delegated OAuth user that was selected. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig?: {
      throwIfNoDelegates?: boolean;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
    };
  }): Promise<T | typeof NO_DELEGATES> {
    const { userProfile, fn, sharedMailboxConfig } = input;
    const maxDelegates = sharedMailboxConfig?.maxDelegates ?? 3;
    const throwIfNoDelegates = sharedMailboxConfig?.throwIfNoDelegates ?? false;
    const preferredDelegateUserId = sharedMailboxConfig?.preferredDelegateUserId;

    if (userProfile.source === 'oauth') {
      const client = this.graphClientFactory.createClientForUser(userProfile.id);
      return fn({ client, clientUserProfileId: userProfile.id });
    }

    // source === 'shared-mailbox': use delegated access
    let delegates = await this.db
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
      return NO_DELEGATES;
    }

    const preferredIdx = delegates.findIndex((d) => d.delegateUserId === preferredDelegateUserId);
    if (preferredIdx > 0) {
      delegates = swapIndices(delegates, 0, preferredIdx);
    }
    const candidates = delegates.slice(0, maxDelegates);

    for (const delegate of candidates) {
      const client = this.graphClientFactory.createClientForUser(delegate.delegateUserId);
      try {
        return await fn({ client, clientUserProfileId: delegate.delegateUserId });
      } catch (error) {
        if (error instanceof GraphError && (error.statusCode === 401 || error.statusCode === 403)) {
          continue;
        }
        throw error;
      }
    }

    this.logger.warn({ ownerUserId: userProfile.id, msg: 'All delegates exhausted (401/403)' });
    throw new AllDelegatesFailedError(userProfile.id);
  }
}
