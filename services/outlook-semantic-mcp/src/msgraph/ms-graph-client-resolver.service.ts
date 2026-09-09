import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, inArray, isNotNull, sql } from 'drizzle-orm';
import { swapIndices } from 'remeda';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  SOURCES_WITH_OWN_CREDENTIALS,
  UserProfile,
  userProfiles,
} from '~/db';
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
    super(`All credentials exhausted (401/403) for owner: ${ownerUserId}`);
    this.name = 'AllDelegatesFailedError';
  }
}

export interface GraphClientResolveOptions {
  /**
   * When `false`, skip delegate rotation and use the signed-in user's own Graph token.
   * Interactive MCP tool calls set this so a dead Microsoft grant forces re-auth instead
   * of silently finishing as a colleague. Background jobs leave the default (`true`).
   *
   * `false` therefore marks a call that has a caller to answer to, and commands use it to
   * decide whether a revoked grant propagates: an MCP client needs the error to reach its
   * re-auth path, while a queue or webhook trigger has nobody to prompt and keeps recording
   * a failed run instead.
   */
  allowDelegateFallback?: boolean;
}

function preferDelegate(
  delegates: { delegateUserId: string }[],
  preferredDelegateUserId: string | undefined,
): { delegateUserId: string }[] {
  const preferredIdx = delegates.findIndex((d) => d.delegateUserId === preferredDelegateUserId);
  if (preferredIdx > 0) {
    return swapIndices(delegates, 0, preferredIdx);
  }
  return delegates;
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
   *   A 401/403 propagates rather than becoming `AllDelegatesFailedError`.
   * - **shared-mailbox profiles** — queries `delegatedAccessAccounts` for full-access delegates
   *   ordered by `lastVerifiedAt DESC NULLS LAST`, then tries each in turn (up to `maxDelegates`,
   *   default 3). A 401/403 from Graph moves to the next candidate; any other error is rethrown
   *   immediately. If all candidates exhaust with 401/403, `AllDelegatesFailedError` is thrown.
   * - **shared-mailbox-with-login profiles** — same candidate loop, but the mailbox's own token is
   *   tried first. `preferredDelegateUserId` is swapped to the front of the *delegate* segment only,
   *   so a stale preferred delegate cannot outrank the mailbox's own credential.
   *   When `allowDelegateFallback` is `false` (interactive tool calls), only the mailbox's own
   *   token is used: a 401/403 or revoked grant propagates so the signed-in user re-authenticates.
   *
   * Graph paths inside `fn` should use the `userProfile` from the outer scope
   * (e.g. `users/${userProfile.email}/…`) whenever a delegate token might be selected.
   *
   * Return type depends on `throwIfNoDelegates`:
   * - omitted / `false` → returns `NO_DELEGATES` symbol when no credentials exist; use `isNoDelegates()` to check
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
       * For shared-mailbox profiles this is the delegated user that was selected.
       * For shared-mailbox-with-login this is the mailbox itself when self wins, otherwise a delegate. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig: {
      throwIfNoDelegates: true;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
      allowDelegateFallback?: boolean;
    };
  }): Promise<T>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: {
      client: Client;
      /** The user profile ID the client is authenticated as.
       * For `oauth` profiles this equals `userProfile.id`.
       * For shared-mailbox profiles this is the delegated user that was selected.
       * For shared-mailbox-with-login this is the mailbox itself when self wins, otherwise a delegate. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig?: {
      throwIfNoDelegates?: false;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
      allowDelegateFallback?: boolean;
    };
  }): Promise<T | typeof NO_DELEGATES>;

  public async run<T>(input: {
    userProfile: NonNullishProps<UserProfile, 'email'>;
    fn: (ctx: {
      client: Client;
      /** The user profile ID the client is authenticated as.
       * For `oauth` profiles this equals `userProfile.id`.
       * For shared-mailbox profiles this is the delegated user that was selected.
       * For shared-mailbox-with-login this is the mailbox itself when self wins, otherwise a delegate. */
      clientUserProfileId: string;
    }) => Promise<T>;
    sharedMailboxConfig?: {
      throwIfNoDelegates?: boolean;
      maxDelegates?: number;
      preferredDelegateUserId?: string;
      allowDelegateFallback?: boolean;
    };
  }): Promise<T | typeof NO_DELEGATES> {
    const { userProfile, fn, sharedMailboxConfig } = input;
    const maxDelegates = sharedMailboxConfig?.maxDelegates ?? 3;
    const throwIfNoDelegates = sharedMailboxConfig?.throwIfNoDelegates ?? false;
    const preferredDelegateUserId = sharedMailboxConfig?.preferredDelegateUserId;
    const allowDelegateFallback = sharedMailboxConfig?.allowDelegateFallback ?? true;

    if (
      userProfile.source === 'oauth' ||
      // Interactive tool calls: use the signed-in user's own token only. A dead Microsoft
      // grant must reach the caller so they re-authenticate instead of finishing as a delegate.
      (userProfile.source === 'shared-mailbox-with-login' && !allowDelegateFallback)
    ) {
      const client = this.graphClientFactory.createClientForUser(userProfile.id);
      return fn({ client, clientUserProfileId: userProfile.id });
    }

    const delegates = await this.db
      .select({ delegateUserId: delegatedAccessAccounts.delegateUserId })
      .from(delegatedAccessAccounts)
      .innerJoin(
        userProfiles,
        and(
          eq(userProfiles.id, delegatedAccessAccounts.delegateUserId),
          inArray(userProfiles.source, SOURCES_WITH_OWN_CREDENTIALS),
          isNotNull(userProfiles.accessToken),
        ),
      )
      .where(
        and(
          eq(delegatedAccessAccounts.ownerUserId, userProfile.id),
          eq(delegatedAccessAccounts.hasFullDelegatedAccess, true),
        ),
      )
      .orderBy(sql`${delegatedAccessAccounts.lastVerifiedAt} DESC NULLS LAST`);

    const ordered = preferDelegate(delegates, preferredDelegateUserId);
    const candidates = userProfile.accessToken
      ? [{ delegateUserId: userProfile.id }, ...ordered]
      : ordered;

    if (candidates.length === 0) {
      if (throwIfNoDelegates) {
        throw new NoDelegatesFoundError(userProfile.id);
      }
      return NO_DELEGATES;
    }

    const tried = candidates.slice(0, maxDelegates);

    for (const delegate of tried) {
      const client = this.graphClientFactory.createClientForUser(delegate.delegateUserId);
      try {
        return await fn({ client, clientUserProfileId: delegate.delegateUserId });
      } catch (error) {
        // 401/403 cycle to the next candidate. A permanent Microsoft grant failure
        // (`invalid_grant`) already revoked that delegate's own MCP tokens — keep walking
        // so one dead delegate does not fail the owner's request.
        if (isUpstreamCredentialRevokedError(error)) {
          this.logger.warn({
            ownerUserId: userProfile.id,
            delegateUserId: delegate.delegateUserId,
            msg: "Delegate Microsoft grant is permanently invalid; revoked that delegate's own MCP sessions and continuing with the next candidate",
          });
          continue;
        }
        if (error instanceof GraphError && (error.statusCode === 401 || error.statusCode === 403)) {
          continue;
        }
        throw error;
      }
    }

    this.logger.warn({ ownerUserId: userProfile.id, msg: 'All credentials exhausted (401/403)' });
    throw new AllDelegatesFailedError(userProfile.id);
  }
}
