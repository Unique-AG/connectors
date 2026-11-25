import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { createSmeared, smearEmail } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, inArray, isNotNull, isNull, lt, lte, notInArray, or, sql } from 'drizzle-orm';
import { alias } from 'drizzle-orm/pg-core';
import { Span } from 'nestjs-otel';
import { last } from 'remeda';
import { AppConfig, appConfig, DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  SOURCES_WITH_DELEGATE_FALLBACK,
  SOURCES_WITH_OWN_CREDENTIALS,
  type UserProfileSource,
  userProfiles,
} from '~/db';
import { DelegatedAccessMetricsService } from '~/features/metrics/delegated-access-metrics.service';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { NewTrace } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { makeDefaultOnErrorHandler, withRetryAttempts } from '~/utils/with-retry-attempts';
import {
  getDelegatedAccessErrorInfo,
  isDelegatedAccessNotAvailableError,
} from '../utils/is-delegated-access-not-available-error';

export const DISCOVER_DELEGATED_ACCESS_CACHE_KEY = `DiscoverDelegatedAccess`;
export const DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES = 10;

type DiscoverDelegatedAccessDecision =
  | { action: 'proceed'; cycleStartedAt: Date; runId: string }
  | { action: 'skip'; reason: string };

type DelegateOutcome = 'discovered' | 'failed' | 'revoked';

@Injectable()
export class DiscoverDelegatedAccessCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    @Inject(appConfig.KEY) private readonly appConfiguration: AppConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly persistentCacheService: PersistentCacheService,
    private readonly metrics: DelegatedAccessMetricsService,
  ) {}

  @NewTrace('discover-delegated-access')
  public async run({ newCycleRequestedAt }: { newCycleRequestedAt?: number }): Promise<void> {
    if (this.config.scan === 'disabled') {
      this.logger.log({
        msg: `Skipped running delegated access discovery. Reason: delegated access is disabled`,
      });
      return;
    }
    await this.metrics.measureDiscoverRun(async () => {
      const decision = await this.decide({ newCycleRequestedAt });
      if (decision.action === 'skip') {
        this.logger.log({
          msg: `Skipped running delegated access discovery. Reason: ${decision.reason}`,
        });
        return;
      }

      let finalState: 'ready' | 'failed';
      let delegateOutcomes: Record<DelegateOutcome, number> | undefined;
      try {
        delegateOutcomes = await this.runDiscoveryInBatches(
          decision.cycleStartedAt,
          decision.runId,
        );
        finalState = 'ready';
      } catch (error) {
        this.logger.error({
          msg: `Failed to run delegated access discovery`,
          cycleStartedAt: decision.cycleStartedAt.toISOString(),
          err: error,
        });
        finalState = 'failed';
      }
      const ownsClaim = await this.updateClaim(decision.runId, { state: finalState });
      if (!ownsClaim) {
        // Another run took over after this one stopped making progress; its state stands.
        this.logger.warn({
          msg: 'Delegated access discovery finished after another run took over; left its state alone',
          finalState,
          delegateOutcomes,
        });
        return;
      }

      await this.logDiscoverySummary(finalState, delegateOutcomes);
    });
  }

  private async logDiscoverySummary(
    finalState: string,
    delegateOutcomes: Record<DelegateOutcome, number> | undefined,
  ): Promise<void> {
    try {
      const delegateProfiles = alias(userProfiles, 'delegate_profiles');
      const ownerProfiles = alias(userProfiles, 'owner_profiles');

      const rows = await this.db
        .select({
          delegateEmail: delegateProfiles.email,
          ownerEmails: sql<(string | null)[]>`ARRAY_AGG(${ownerProfiles.email})`,
        })
        .from(delegatedAccessAccounts)
        .innerJoin(
          delegateProfiles,
          eq(delegatedAccessAccounts.delegateUserId, delegateProfiles.id),
        )
        .innerJoin(ownerProfiles, eq(delegatedAccessAccounts.ownerUserId, ownerProfiles.id))
        .groupBy(delegateProfiles.email);

      // An array (not an object keyed by email) avoids distinct addresses collapsing
      // to the same smeared key and overwriting each other under conceal mode.
      const delegatedAccess = rows.map((row) => ({
        delegate: smearEmail(createSmeared(row.delegateEmail ?? '')),
        owners: row.ownerEmails.map((email) => smearEmail(createSmeared(email ?? ''))),
      }));

      this.logger.log({
        msg: `Delegated access discovery completed, final state: ${finalState}`,
        delegateOutcomes,
        delegatesWithAccess: rows.length,
        delegatedAccess,
      });
    } catch (error) {
      this.logger.warn({
        msg: `Failed to log delegated access discovery summary`,
        err: error,
      });
    }
  }

  /**
   * Processes every delegate the cycle has not discovered yet, so a run after a crash or a failed
   * delegate picks up only what is left. One delegate failing does not stop the others.
   */
  @Span()
  private async runDiscoveryInBatches(
    cycleStartedAt: Date,
    runId: string,
  ): Promise<Record<DelegateOutcome, number>> {
    const outcomes: Record<DelegateOutcome, number> = { discovered: 0, failed: 0, revoked: 0 };
    let delegatesBatch = await this.fetchBatch({
      includeSharedMailboxes: false,
      pendingDiscoveryBefore: cycleStartedAt,
    });

    while (delegatesBatch.length) {
      for (const { userProfileId: delegateUserId } of delegatesBatch) {
        const outcome = await this.runDiscoveryForDelegatedUser(delegateUserId, runId);
        outcomes[outcome] += 1;
      }

      delegatesBatch = await this.fetchBatch({
        lastFetchedId: last(delegatesBatch)?.userProfileId,
        includeSharedMailboxes: false,
        pendingDiscoveryBefore: cycleStartedAt,
      });
    }
    return outcomes;
  }

  @Span()
  private async runDiscoveryForDelegatedUser(
    delegateUserId: string,
    runId: string,
  ): Promise<DelegateOutcome> {
    // Stamped instead of the completion time: a cycle that starts while these checks run must
    // still find the delegate pending.
    const checksStartedAt = new Date();
    try {
      const failedOwnerChecks = await this.metrics.measureDiscoverUser(() =>
        this.runBatchForDelegatedUser(delegateUserId, runId),
      );
      if (failedOwnerChecks > 0) {
        this.logger.warn({
          msg: 'Delegated access discovery left delegate pending: owner checks failed; kept its records and will retry it',
          delegateUserId,
          failedOwnerChecks,
        });
        return 'failed';
      }
      await this.db
        .update(userProfiles)
        .set({ delegatedAccessDiscoveredAt: checksStartedAt })
        .where(
          and(
            eq(userProfiles.id, delegateUserId),
            // A stale run that finishes late must not move back a newer run's stamp.
            or(
              isNull(userProfiles.delegatedAccessDiscoveredAt),
              lt(userProfiles.delegatedAccessDiscoveredAt, checksStartedAt),
            ),
          ),
        );
      return 'discovered';
    } catch (error) {
      if (isUpstreamCredentialRevokedError(error)) {
        return await this.clearRevokedDelegate(delegateUserId);
      }

      // A token refresh that is backing off, a 401 after a refresh, rate limits that outlasted
      // the retries, or a failed write. The records stay as they were and the delegate is retried
      // later in the cycle.
      this.logger.warn({
        msg: 'Delegated access discovery failed for delegate; kept its records and will retry it',
        delegateUserId,
        ...getDelegatedAccessErrorInfo(error),
        err: error,
      });
      return 'failed';
    }
  }

  /**
   * The delegate's Microsoft grant is permanently invalid (revoked consent, expired refresh
   * token). The MCP must not expose mailboxes it can no longer authenticate against, so their
   * access records go. They are re-discovered once the user signs in again.
   */
  private async clearRevokedDelegate(delegateUserId: string): Promise<DelegateOutcome> {
    try {
      await this.db
        .delete(delegatedAccessAccounts)
        .where(eq(delegatedAccessAccounts.delegateUserId, delegateUserId));
    } catch (error) {
      this.logger.warn({
        msg: "Failed to clear a revoked delegate's access records; will retry it",
        delegateUserId,
        err: error,
      });
      return 'failed';
    }
    this.logger.warn({
      delegateUserId,
      msg: "Cleared delegated access records: the delegate's Microsoft grant is permanently invalid",
    });
    return 'revoked';
  }

  @Span()
  /** Returns how many owner checks failed; the delegate only counts as discovered when none did. */
  private async runBatchForDelegatedUser(delegateUserId: string, runId: string): Promise<number> {
    const client = this.graphClientFactory.createClientForUser(delegateUserId);
    let failedOwnerChecks = 0;
    let ownersBatch = await this.fetchBatch({
      excludedProfileIds: [delegateUserId],
      includeSharedMailboxes: true,
    });

    while (ownersBatch.length) {
      // Every check settles first, so an ordinary 401 that rejects early cannot hide a revoked
      // grant that another check reports.
      const settled = await Promise.allSettled(
        ownersBatch.map(
          ({ userProfileId: ownerUserId, email: ownerEmail, source: ownerSource }) => {
            return withRetryAttempts<{ status: 'success' } | { status: 'failed'; error: unknown }>({
              fn: async () => {
                await this.updateDelegatedAccess({
                  ownerUserId,
                  ownerEmail,
                  ownerSource,
                  client,
                  delegateUserId,
                  runId,
                });
                return { status: 'success' as const };
              },
              onError: makeDefaultOnErrorHandler((err) => {
                this.logger.warn({
                  msg: `Delegated access discovery failed for accounts pair. Process will continue`,
                  delegateUserId,
                  ownerUserId,
                  ownerEmail: smearEmail(createSmeared(ownerEmail)),
                  ownerSource,
                  err,
                });
                return { status: 'failed' as const, error: err };
              }),
            });
          },
        ),
      );
      const rejections = settled.flatMap((r) => (r.status === 'rejected' ? [r.reason] : []));
      if (rejections.length) {
        throw rejections.find(isUpstreamCredentialRevokedError) ?? rejections[0];
      }
      const batchResults = settled.flatMap((r) => (r.status === 'fulfilled' ? [r.value] : []));

      const successCount = batchResults.filter((r) => r.status === 'success').length;
      const failedCount = batchResults.filter((r) => r.status === 'failed').length;
      failedOwnerChecks += failedCount;
      this.logger.log({
        delegateUserId,
        successCount,
        failedCount,
        msg: 'Owner batch processed',
      });

      await this.updateClaim(runId);

      ownersBatch = await this.fetchBatch({
        lastFetchedId: last(ownersBatch)?.userProfileId,
        excludedProfileIds: [delegateUserId],
        includeSharedMailboxes: true,
      });
    }
    return failedOwnerChecks;
  }

  /**
   * Claims the run unless another one is making progress. A new cycle moves `cycleStartedAt` to
   * now so every delegate is pending again; otherwise the run continues the current cycle. The
   * claim's `runId` is what the run's heartbeat and final state write must still match.
   */
  @Span()
  public async decide({
    newCycleRequestedAt,
  }: {
    newCycleRequestedAt?: number;
  }): Promise<DiscoverDelegatedAccessDecision> {
    return this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, create, update }): Promise<DiscoverDelegatedAccessDecision> => {
        const now = Date.now();

        const runId = randomUUID();
        if (!currentValue) {
          await create({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              state: 'running',
              runId,
              cycleStartedAt: now,
              lastProgressRegisteredAt: now,
            },
          });
          return { action: 'proceed', cycleStartedAt: new Date(now), runId };
        }

        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
        const { state, lastProgressRegisteredAt, cycleStartedAt } = currentValue.payload;
        // RabbitMQ redelivers the request a killed run was processing. It was made before the cycle
        // it started, so it continues that cycle instead of starting another one.
        const startsNewCycle =
          newCycleRequestedAt !== undefined &&
          (cycleStartedAt === undefined ||
            cycleStartedAt === null ||
            newCycleRequestedAt > cycleStartedAt);

        const noProgressThresholdMs =
          DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES * 60_000;
        if (state === 'running' && now - lastProgressRegisteredAt < noProgressThresholdMs) {
          if (startsNewCycle) {
            // The running run finishes the cycle it started with. Once it ends, the recovery cron
            // finds every delegate pending against the new start, so the new cycle is not lost.
            await update({
              dataType: 'DelegatedAccessDiscovery',
              payload: { ...currentValue.payload, cycleStartedAt: now },
            });
          }
          return {
            action: 'skip',
            reason: `Skipped running discovery for delegated permissions, another discovery in progress`,
          };
        }

        const nextCycleStartedAt = startsNewCycle ? now : (cycleStartedAt ?? now);
        await update({
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            state: 'running',
            runId,
            cycleStartedAt: nextCycleStartedAt,
            lastProgressRegisteredAt: now,
          },
        });
        return { action: 'proceed', cycleStartedAt: new Date(nextCycleStartedAt), runId };
      },
    );
  }

  /** Whether the current cycle still has delegates to discover whose token is not backing off. */
  public async hasPendingDelegates(cycleStartedAt: Date): Promise<boolean> {
    const pending = await this.fetchBatch({
      includeSharedMailboxes: false,
      pendingDiscoveryBefore: cycleStartedAt,
    });
    return pending.length > 0;
  }

  private async fetchBatch({
    lastFetchedId,
    excludedProfileIds,
    includeSharedMailboxes,
    pendingDiscoveryBefore,
  }: {
    lastFetchedId?: string;
    excludedProfileIds?: string[];
    includeSharedMailboxes: boolean;
    pendingDiscoveryBefore?: Date;
  }): Promise<{ userProfileId: string; email: string; source: UserProfileSource }[]> {
    const conditionsByMailbox = includeSharedMailboxes
      ? or(
          and(
            inArray(userProfiles.source, SOURCES_WITH_OWN_CREDENTIALS),
            isNotNull(userProfiles.accessToken),
          ),
          inArray(userProfiles.source, SOURCES_WITH_DELEGATE_FALLBACK),
        )
      : and(
          inArray(userProfiles.source, SOURCES_WITH_OWN_CREDENTIALS),
          isNotNull(userProfiles.accessToken),
        );

    const items = await this.db
      .select({
        userProfileId: userProfiles.id,
        email: userProfiles.email,
        source: userProfiles.source,
      })
      .from(userProfiles)
      .where(
        and(
          lastFetchedId ? gt(userProfiles.id, lastFetchedId) : undefined,
          isNotNull(userProfiles.email),
          excludedProfileIds && excludedProfileIds.length > 0
            ? notInArray(userProfiles.id, excludedProfileIds)
            : undefined,
          conditionsByMailbox,
          pendingDiscoveryBefore
            ? and(
                or(
                  isNull(userProfiles.delegatedAccessDiscoveredAt),
                  lt(userProfiles.delegatedAccessDiscoveredAt, pendingDiscoveryBefore),
                ),
                // A delegate whose token refresh is backing off would only fail again.
                or(
                  isNull(userProfiles.tokenRefreshRetryAt),
                  lte(userProfiles.tokenRefreshRetryAt, new Date()),
                ),
              )
            : undefined,
        ),
      )
      .orderBy(userProfiles.id)
      // An owner batch is checked against Graph in parallel, so this is the discovery concurrency.
      .limit(50);

    // Type casting is safe because isNotNull(userProfiles.email) ensures email is not null
    return items as { userProfileId: string; email: string; source: UserProfileSource }[];
  }

  private async updateDelegatedAccess({
    ownerEmail,
    delegateUserId,
    ownerUserId,
    ownerSource,
    client,
    runId,
  }: {
    client: Client;
    delegateUserId: string;
    ownerUserId: string;
    ownerEmail: string | null;
    ownerSource: UserProfileSource;
    runId: string;
  }): Promise<void> {
    if (!ownerEmail) {
      this.logger.warn({ ownerUserId, msg: 'Skipping owner with null email' });
      return;
    }

    try {
      const apiEndpoint =
        SOURCES_WITH_DELEGATE_FALLBACK.includes(ownerSource) ||
        this.config.scan === 'full_access_only'
          ? 'messages'
          : 'mailFolders';
      await client.api(`/users/${ownerEmail}/${apiEndpoint}`).top(1).select('id').get();

      const now = new Date();
      const fieldsToUpsert =
        apiEndpoint === 'messages'
          ? {
              lastDiscoveredAt: now,
              lastVerifiedAt: now,
              hasFullDelegatedAccess: true,
            }
          : {
              lastDiscoveredAt: now,
              // if we did not check using the `messages` endpoint we do not flip hasFullDelegatedAccess to
              // false because the sync-delegated-access.command.ts will flip that flag.
            };

      await this.db
        .insert(delegatedAccessAccounts)
        .values({
          ...fieldsToUpsert,
          delegateUserId,
          ownerUserId,
        })
        .onConflictDoUpdate({
          target: [delegatedAccessAccounts.delegateUserId, delegatedAccessAccounts.ownerUserId],
          set: fieldsToUpsert,
        });

      this.logger.debug({ delegateUserId, ownerUserId, msg: 'Delegated access discovered' });
      await this.updateClaim(runId);
    } catch (error) {
      if (isDelegatedAccessNotAvailableError(error)) {
        await this.db
          .delete(delegatedAccessAccounts)
          .where(
            and(
              eq(delegatedAccessAccounts.delegateUserId, delegateUserId),
              eq(delegatedAccessAccounts.ownerUserId, ownerUserId),
            ),
          );
        this.logger.debug({
          msg: `Delegated access revoked, removed from accounts`,
          delegateUserId,
          ownerUserId,
          ...getDelegatedAccessErrorInfo(error),
          ...(this.appConfiguration.mcpDebugMode ? { err: error } : {}),
        });
        await this.updateClaim(runId);
        return;
      }

      throw error;
    }
  }

  /**
   * Records progress (and the final state, when given) while this run still holds the claim.
   * Returns false once another run has taken it over, so a stale run cannot overwrite it.
   */
  private async updateClaim(
    runId: string,
    changes: { state?: 'ready' | 'failed' } = {},
  ): Promise<boolean> {
    return this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, update }): Promise<boolean> => {
        assert.ok(currentValue);
        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
        if (currentValue.payload.runId !== runId) {
          return false;
        }
        await update({
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            ...currentValue.payload,
            ...changes,
            lastProgressRegisteredAt: Date.now(),
          },
        });
        return true;
      },
    );
  }
}
