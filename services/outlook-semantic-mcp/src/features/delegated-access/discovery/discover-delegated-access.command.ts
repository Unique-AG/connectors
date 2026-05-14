import assert from 'node:assert';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt, inArray, isNotNull, notInArray, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, last } from 'remeda';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  subscriptions,
  userProfiles,
} from '~/db';
import { DelegatedAccessMetricsService } from '~/features/metrics/delegated-access-metrics.service';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { NewTrace } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { Nullish } from '~/utils/nullish';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';

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
        this.logger.error({ msg: `Failed to run delegated access discovery`, err: error });
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
        this.runInnerLoop({
          // For some reason isNonNullish(lastProcessedDelegateId) is not enough for typescript here.
          delegateUserId: lastProcessedDelegateId as string,
          lastProcessedOwnerIdForDelegate: lastProcessedOwnerIdForDelegate,
        }),
      );
    }

    // Continue outer loop from the last processed delegate
    let delegatesBatch = await this.fetchBatch({
      lastFetchedId: lastProcessedDelegateId ?? undefined,
    });

    while (delegatesBatch.length) {
      for (const { userProfileId: delegateUserId } of delegatesBatch) {
        await this.metrics.measureDiscoverUser(() =>
          this.runInnerLoop({
            delegateUserId,
            lastProcessedOwnerIdForDelegate: null,
          }),
        );
        lastProcessedDelegateId = delegateUserId;
      }

      delegatesBatch = await this.fetchBatch({
        lastFetchedId: lastProcessedDelegateId ?? undefined,
      });
    }
  }

  @Span()
  private async runInnerLoop({
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
    });

    while (ownersBatch.length) {
      const batchResults = await Promise.all(
        ownersBatch.map(({ userProfileId: ownerUserId, email: ownerEmail }) => {
          return withRetryAttempts({
            fn: async () => {
              await this.updateDelegatedAccess({
                ownerUserId,
                ownerEmail,
                client,
                delegateUserId,
              });
              return { status: 'success' as const };
            },
            onError: rethrowRateLimitError,
            getResultFailure: (error) => ({ status: 'failed' as const, error }),
          });
        }),
      );

      const successCount = batchResults.filter((r) => r.status === 'success').length;
      const failedCount = batchResults.filter((r) => r.status === 'failed').length;
      this.logger.log({ delegateUserId, successCount, failedCount, msg: 'Owner batch processed' });

      ownersLastFetchedId = last(ownersBatch)?.userProfileId;
      await this.persistentCacheService.setWith(
        DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
        async ({ currentValue, update }): Promise<void> => {
          assert.ok(currentValue);
          assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
          await update({
            dataType: 'DelegatedAccessDiscovery',
            payload: {
              ...currentValue.payload,
              lastProcessedDelegateId: delegateUserId,
              lastProcessedOwnerIdForDelegate: ownersLastFetchedId,
              lastProgressRegisteredAt: Date.now(),
            },
          });
        },
      );

      ownersBatch = await this.fetchBatch({
        lastFetchedId: ownersLastFetchedId ?? undefined,
        excludedProfileIds: [delegateUserId],
      });
    }

    // Inner loop complete for this delegate — clear the owner cursor
    await this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, update }): Promise<void> => {
        assert.ok(currentValue);
        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
        await update({
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            ...currentValue.payload,
            lastProcessedDelegateId: delegateUserId,
            lastProcessedOwnerIdForDelegate: null,
            lastProgressRegisteredAt: Date.now(),
          },
        });
      },
    );
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
  }: {
    lastFetchedId?: string;
    excludedProfileIds?: string[];
  }): Promise<{ userProfileId: string; email: string }[]> {
    const activeSubscriptions = this.db
      .select({ userProfileId: subscriptions.userProfileId })
      .from(subscriptions)
      .where(and(gt(subscriptions.expiresAt, sql`NOW()`)));

    const items = await this.db
      .select({ userProfileId: userProfiles.id, email: userProfiles.email })
      .from(userProfiles)
      .where(
        and(
          lastFetchedId ? gt(userProfiles.id, lastFetchedId) : undefined,
          isNotNull(userProfiles.email),
          excludedProfileIds && excludedProfileIds.length > 0
            ? notInArray(userProfiles.id, excludedProfileIds)
            : undefined,
          inArray(userProfiles.id, activeSubscriptions),
        ),
      )
      .orderBy(userProfiles.id)
      .limit(100);

    // Type casting is safe because isNotNull(userProfiles.email) ensures the email is not null
    return items as { userProfileId: string; email: string }[];
  }

  private async updateDelegatedAccess({
    ownerEmail,
    delegateUserId,
    ownerUserId,
    client,
  }: {
    client: Client;
    delegateUserId: string;
    ownerUserId: string;
    ownerEmail: string | null;
  }): Promise<void> {
    if (!ownerEmail) {
      this.logger.warn({ ownerUserId, msg: 'Skipping owner with null email' });
      return;
    }

    try {
      const apiEndpoint = this.config.scan === 'fullAccessOnly' ? `messages` : 'mailFolders';
      await client.api(`/users/${ownerEmail}/${apiEndpoint}`).top(1).select('id').get();

      const now = new Date();
      const fieldsToUpsert =
        apiEndpoint === 'messages'
          ? {
              lastDiscoveredAt: now,
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
      await this.updateProgressTimestamp();
    } catch (error) {
      if (error instanceof GraphError) {
        if (error.statusCode === 403 || error.statusCode === 404) {
          await this.db
            .delete(delegatedAccessAccounts)
            .where(
              and(
                eq(delegatedAccessAccounts.delegateUserId, delegateUserId),
                eq(delegatedAccessAccounts.ownerUserId, ownerUserId),
              ),
            );
          this.logger.debug({
            delegateUserId,
            ownerUserId,
            statusCode: error.statusCode,
            msg: 'Delegated access revoked, removed from accounts',
          });
          await this.updateProgressTimestamp();
          return;
        }

        if (error.statusCode === 429 || (error.statusCode >= 500 && error.statusCode < 600)) {
          this.logger.debug({
            delegateUserId,
            ownerUserId,
            statusCode: error.statusCode,
            msg: 'Transient error during discovery',
          });
          throw error;
        }
      }

      this.logger.debug({
        delegateUserId,
        ownerUserId,
        error,
        msg: 'Unexpected error during delegated access discovery',
      });

      throw error;
    }
  }

  private async updateProgressTimestamp(): Promise<void> {
    await this.persistentCacheService.setWith(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      async ({ currentValue, update }): Promise<void> => {
        assert.ok(currentValue);
        assert.ok(currentValue.dataType === 'DelegatedAccessDiscovery');
        await update({
          dataType: 'DelegatedAccessDiscovery',
          payload: {
            ...currentValue.payload,
            lastProgressRegisteredAt: Date.now(),
          },
        });
      },
    );
  }
}
