import assert from 'node:assert';
import { createSmeared, smearEmail } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, isNotNull, notInArray, or, sql } from 'drizzle-orm';
import { alias } from 'drizzle-orm/pg-core';
import { Span } from 'nestjs-otel';
import { isNonNullish, last } from 'remeda';
import { AppConfig, appConfig, DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts, userProfiles } from '~/db';
import { DelegatedAccessMetricsService } from '~/features/metrics/delegated-access-metrics.service';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { NewTrace } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { isTokenExpiredError } from '~/utils/is-token-expired-error';
import { Nullish } from '~/utils/nullish';
import { makeDefaultOnErrorHandler, withRetryAttempts } from '~/utils/with-retry-attempts';
import {
  getDelegatedAccessErrorInfo,
  isDelegatedAccessNotAvailableError,
} from '../utils/is-delegated-access-not-available-error';

export const DISCOVER_DELEGATED_ACCESS_CACHE_KEY = `DiscoverDelegatedAccess`;
export const DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES = 10;

type DiscoverDelegatedAccessDecision =
  | {
      action: 'proceed';
      lastProcessedDelegateId: Nullish<string>;
      lastProcessedOwnerIdForDelegate: Nullish<string>;
    }
  | { action: 'skip'; reason: string };

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
  public async run(): Promise<void> {
    if (this.config.scan === 'disabled') {
      this.logger.log({
        msg: `Skipped running delegated access discovery. Reason: delegated access is disabled`,
      });
      return;
    }
    await this.metrics.measureDiscoverRun(async () => {
      const decision = await this.decide();
      if (decision.action === 'skip') {
        this.logger.log({
          msg: `Skipped running delegated access discovery. Reason: ${decision.reason}`,
        });
        return;
      }

      let finalState: 'ready' | 'failed';
      try {
        await this.runDiscoveryInBatches(
          decision.lastProcessedDelegateId,
          decision.lastProcessedOwnerIdForDelegate,
        );
        finalState = 'ready';
      } catch (error) {
        const currentCachedValue = await this.persistentCacheService.get(
          DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
          `DelegatedAccessDiscovery`,
        );
        const payload = currentCachedValue?.payload;
        this.logger.error({
          msg: `Failed to run delegated access discovery`,
          lastProcessedDelegateId: payload?.lastProcessedDelegateId,
          lastProcessedOwnerIdForDelegate: payload?.lastProcessedOwnerIdForDelegate,
          lastProgressRegisteredAt: payload?.lastProgressRegisteredAt,
          err: error,
        });
        finalState = 'failed';
      }
      await this.persistentCacheService.setWith(
        DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
        async ({ currentValue, update }): Promise<void> => {
          assert.ok(currentValue);
          assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
          await update({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              ...currentValue.payload,
              state: finalState,
              lastProgressRegisteredAt: Date.now(),
            },
          });
        },
      );

      // Best-effort summary: a logging/query failure here must not flip the
      // already-committed discovery outcome into a failed run.
      try {
        await this.logDiscoverySummary(finalState);
      } catch (error) {
        this.logger.warn({
          msg: `Failed to log delegated access discovery summary`,
          err: error,
        });
      }
    });
  }

  private async logDiscoverySummary(finalState: string): Promise<void> {
    const delegateProfiles = alias(userProfiles, 'delegate_profiles');
    const ownerProfiles = alias(userProfiles, 'owner_profiles');

    const rows = await this.db
      .select({
        delegateEmail: delegateProfiles.email,
        ownerEmails: sql<(string | null)[]>`ARRAY_AGG(${ownerProfiles.email})`,
      })
      .from(delegatedAccessAccounts)
      .innerJoin(delegateProfiles, eq(delegatedAccessAccounts.delegateUserId, delegateProfiles.id))
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
      delegatesWithAccess: rows.length,
      delegatedAccess,
    });
  }

  @Span()
  private async runDiscoveryInBatches(
    lastProcessedDelegateId: Nullish<string>,
    lastProcessedOwnerIdForDelegate: Nullish<string>,
  ): Promise<void> {
    // If we have an in-progress delegate, resume its inner loop first
    if (isNonNullish(lastProcessedDelegateId) && isNonNullish(lastProcessedOwnerIdForDelegate)) {
      await this.metrics.measureDiscoverUser(() =>
        this.runDiscoveryForDelegatedUser({
          // For some reason isNonNullish(lastProcessedDelegateId) is not enough for typescript here.
          delegateUserId: lastProcessedDelegateId as string,
          lastProcessedOwnerIdForDelegate: lastProcessedOwnerIdForDelegate,
        }),
      );
    }

    // Continue outer loop from the last processed delegate
    let delegatesBatch = await this.fetchBatch({
      lastFetchedId: lastProcessedDelegateId ?? undefined,
      includeSharedMailboxes: false,
    });

    while (delegatesBatch.length) {
      for (const { userProfileId: delegateUserId } of delegatesBatch) {
        await this.metrics.measureDiscoverUser(() =>
          this.runDiscoveryForDelegatedUser({
            delegateUserId,
            lastProcessedOwnerIdForDelegate: null,
          }),
        );
        lastProcessedDelegateId = delegateUserId;
      }

      delegatesBatch = await this.fetchBatch({
        lastFetchedId: lastProcessedDelegateId ?? undefined,
        includeSharedMailboxes: false,
      });
    }
  }

  @Span()
  private async runDiscoveryForDelegatedUser({
    delegateUserId,
    lastProcessedOwnerIdForDelegate,
  }: {
    delegateUserId: string;
    lastProcessedOwnerIdForDelegate: Nullish<string>;
  }): Promise<void> {
    try {
      await this.runBatchForDelegatedUser({ delegateUserId, lastProcessedOwnerIdForDelegate });
    } catch (error) {
      if (!isTokenExpiredError(error)) {
        // Rate limit errors that exhausted retries (and other unexpected errors) propagate to run(),
        // which sets finalState = 'failed'. The DelegatedAccessRecoverySchedulerService then detects
        // the failed state and retriggers discovery.
        throw error;
      }

      // The delegate's OAuth token cannot be refreshed (revoked consent, expired refresh token).
      // Clearing their access records is the safe choice: the MCP must not expose mailboxes it
      // can no longer authenticate against. Entries will be re-discovered when the user
      // re-authenticates and the next discovery run processes this delegate again.
      await this.db
        .delete(delegatedAccessAccounts)
        .where(eq(delegatedAccessAccounts.delegateUserId, delegateUserId));
      this.logger.warn({
        delegateUserId,
        msg: 'Cleared delegated access records: delegate token refresh failed, skipping remaining owner batches for this delegate',
      });
      await this.updateProgress({
        lastProcessedDelegateId: delegateUserId,
        lastProcessedOwnerIdForDelegate: null,
      });
      return;
    }
  }

  @Span()
  private async runBatchForDelegatedUser({
    delegateUserId,
    lastProcessedOwnerIdForDelegate,
  }: {
    delegateUserId: string;
    lastProcessedOwnerIdForDelegate: Nullish<string>;
  }): Promise<void> {
    const client = this.graphClientFactory.createClientForUser(delegateUserId);
    let ownersLastFetchedId: Nullish<string> = lastProcessedOwnerIdForDelegate;
    let ownersBatch = await this.fetchBatch({
      lastFetchedId: ownersLastFetchedId ?? undefined,
      excludedProfileIds: [delegateUserId],
      includeSharedMailboxes: true,
    });

    while (ownersBatch.length) {
      const batchResults = await Promise.all(
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

      const successCount = batchResults.filter((r) => r.status === 'success').length;
      const failedCount = batchResults.filter((r) => r.status === 'failed').length;
      this.logger.log({
        delegateUserId,
        successCount,
        failedCount,
        msg: 'Owner batch processed',
      });

      ownersLastFetchedId = last(ownersBatch)?.userProfileId;
      await this.updateProgress({
        lastProcessedDelegateId: delegateUserId,
        lastProcessedOwnerIdForDelegate: ownersLastFetchedId,
      });

      ownersBatch = await this.fetchBatch({
        lastFetchedId: ownersLastFetchedId ?? undefined,
        excludedProfileIds: [delegateUserId],
        includeSharedMailboxes: true,
      });
    }

    // Inner loop complete for this delegate — clear the owner cursor
    await this.updateProgress({
      lastProcessedDelegateId: delegateUserId,
      lastProcessedOwnerIdForDelegate: null,
    });
  }

  @Span()
  public async decide(): Promise<DiscoverDelegatedAccessDecision> {
    return this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, create, update }): Promise<DiscoverDelegatedAccessDecision> => {
        if (!currentValue) {
          await create({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              state: 'running',
              lastProcessedDelegateId: null,
              lastProcessedOwnerIdForDelegate: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedDelegateId: null,
            lastProcessedOwnerIdForDelegate: null,
          };
        }

        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');

        if (currentValue.payload.state === 'ready') {
          await update({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              state: 'running',
              lastProcessedDelegateId: null,
              lastProcessedOwnerIdForDelegate: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedDelegateId: null,
            lastProcessedOwnerIdForDelegate: null,
          };
        }

        if (currentValue.payload.state === 'failed') {
          await update({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              state: 'running',
              lastProcessedDelegateId: currentValue.payload.lastProcessedDelegateId,
              lastProcessedOwnerIdForDelegate: currentValue.payload.lastProcessedOwnerIdForDelegate,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedDelegateId: currentValue.payload.lastProcessedDelegateId,
            lastProcessedOwnerIdForDelegate: currentValue.payload.lastProcessedOwnerIdForDelegate,
          };
        }

        const currentTime = new Date();
        currentTime.setMinutes(
          currentTime.getMinutes() - DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES,
        );

        if (currentValue.payload.lastProgressRegisteredAt <= currentTime.getTime()) {
          await update({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              state: 'running',
              lastProcessedDelegateId: currentValue.payload.lastProcessedDelegateId,
              lastProcessedOwnerIdForDelegate: currentValue.payload.lastProcessedOwnerIdForDelegate,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedDelegateId: currentValue.payload.lastProcessedDelegateId,
            lastProcessedOwnerIdForDelegate: currentValue.payload.lastProcessedOwnerIdForDelegate,
          };
        }

        return {
          action: 'skip',
          reason: `Skipped running discovery for delegated permissions, another discovery in progress`,
        };
      },
    );
  }

  private async fetchBatch({
    lastFetchedId,
    excludedProfileIds,
    includeSharedMailboxes,
  }: {
    lastFetchedId?: string;
    excludedProfileIds?: string[];
    includeSharedMailboxes: boolean;
  }): Promise<{ userProfileId: string; email: string; source: string }[]> {
    const conditionsByMailbox = includeSharedMailboxes
      ? or(
          and(eq(userProfiles.source, 'oauth'), isNotNull(userProfiles.accessToken)),
          eq(userProfiles.source, 'shared-mailbox'),
        )
      : and(eq(userProfiles.source, 'oauth'), isNotNull(userProfiles.accessToken));

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
        ),
      )
      .orderBy(userProfiles.id)
      .limit(100);

    // Type casting is safe because isNotNull(userProfiles.email) ensures email is not null
    return items as { userProfileId: string; email: string; source: string }[];
  }

  private async updateDelegatedAccess({
    ownerEmail,
    delegateUserId,
    ownerUserId,
    ownerSource,
    client,
  }: {
    client: Client;
    delegateUserId: string;
    ownerUserId: string;
    ownerEmail: string | null;
    ownerSource: string;
  }): Promise<void> {
    if (!ownerEmail) {
      this.logger.warn({ ownerUserId, msg: 'Skipping owner with null email' });
      return;
    }

    try {
      const apiEndpoint =
        ownerSource === 'shared-mailbox' || this.config.scan === 'full_access_only'
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
      await this.updateProgress();
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
        await this.updateProgress();
        return;
      }

      throw error;
    }
  }

  private async updateProgress(
    cursors?: Partial<{
      lastProcessedDelegateId: string | null;
      lastProcessedOwnerIdForDelegate: string | null;
    }>,
  ): Promise<void> {
    await this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, update }): Promise<void> => {
        assert.ok(currentValue);
        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
        await update({
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            ...currentValue.payload,
            ...(cursors ?? {}),
            lastProgressRegisteredAt: Date.now(),
          },
        });
      },
    );
  }
}
