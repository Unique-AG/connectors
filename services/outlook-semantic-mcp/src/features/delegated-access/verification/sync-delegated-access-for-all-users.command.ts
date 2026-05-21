import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, gt } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts } from '~/db';
import { DelegatedAccessMetricsService } from '~/features/metrics/delegated-access-metrics.service';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { NewTrace } from '~/features/tracing.utils';
import { getRetryAfterMs } from '~/utils/get-retry-after-ms';
import { GenericRateLimitError } from '~/utils/is-rate-limit-error';
import { Nullish } from '~/utils/nullish';
import { makeDefaultOnErrorHandler, withRetryAttempts } from '~/utils/with-retry-attempts';
import { CannotReadErrorReason } from '../utils/data-access-error';
import { SyncDelegatedAccessCommand } from './sync-delegated-access.command';

export const SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY = `SyncDelegatedAccessForAllUsers`;
export const SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_NO_PROGRESS_THRESHOLD_MINUTES = 10;

type SyncDelegatedAccessForAllUsersDecision =
  | { action: 'proceed'; lastProcessedAccountsId: Nullish<string> }
  | { action: 'skip'; reason: string };

@Injectable()
export class SyncDelegatedAccessForAllUsersCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private persistentCacheService: PersistentCacheService,
    private syncDelegatedAccessCommand: SyncDelegatedAccessCommand,
    private readonly metrics: DelegatedAccessMetricsService,
  ) {}

  @NewTrace('sync-delegated-access-scan')
  public async run(): Promise<void> {
    await this.metrics.measureSyncForAllUsersRun(async () => {
      const decision = await this.decide();
      if (decision.action === 'skip') {
        this.logger.log({
          msg: `Skipped running sync delegated access. Reason: ${decision.reason}`,
        });
        return;
      }

      let finalState: 'ready' | 'failed';
      try {
        await this.runSyncInBatches(decision.lastProcessedAccountsId);
        finalState = 'ready';
      } catch (error) {
        this.logger.error({ msg: `Failed to run delegated access sync`, err: error });
        finalState = 'failed';
      }
      await this.persistentCacheService.setWith(
        SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
        async ({ currentValue, update }): Promise<void> => {
          assert.ok(currentValue);
          assert.ok(currentValue.dataType === 'DelegatedAccessVerification');
          await update({
            dataType: 'DelegatedAccessVerification',
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
  private async runSyncInBatches(lastProcessedAccountsId: Nullish<string>): Promise<void> {
    let batch = await this.fetchBatch({ lastProcessedAccountsId });

    while (batch.length) {
      this.logger.log({
        msg: `Running delegated access sync for batch: ${batch.length}`,
        accountsIds: batch.map((item) => item.id).join(', '),
      });
      for (const accounts of batch) {
        await withRetryAttempts({
          fn: () => this.syncDelegatedAccessForAccounts(accounts),
          onError: makeDefaultOnErrorHandler((err) => {
            this.logger.warn({
              msg: `Running delegated access sync for accounts: ${accounts.id} failed`,
              accountsId: accounts.id,
              delegateUserId: accounts.delegateUserId,
              ownerUserId: accounts.ownerUserId,
              err,
            });
            return { status: 'failed', error: err };
          }),
        });
        lastProcessedAccountsId = accounts.id;
        await this.persistentCacheService.setWith(
          SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
          async ({ currentValue, update }): Promise<void> => {
            assert.ok(currentValue);
            assert.ok(currentValue.dataType === 'DelegatedAccessVerification');
            await update({
              dataType: 'DelegatedAccessVerification',
              payload: {
                ...currentValue.payload,
                lastProcessedAccountsId: lastProcessedAccountsId,
                lastProgressRegisteredAt: Date.now(),
              },
            });
          },
        );
      }

      batch = await this.fetchBatch({ lastProcessedAccountsId: lastProcessedAccountsId });
    }
  }

  private async syncDelegatedAccessForAccounts(accounts: {
    id: string;
    delegateUserId: string;
  }): Promise<{ status: 'success' | 'skipped' }> {
    const result = await this.syncDelegatedAccessCommand.run({
      accountsId: accounts.id,
      onProgress: () => this.updateProgressTimestamp(),
    });
    if (result.status !== 'failed') {
      return { status: result.status };
    }

    const tokenExpiredError = result.errors.find(
      (error) => error.reason === CannotReadErrorReason.TokenExpired,
    );

    if (tokenExpiredError) {
      // We remove the user with token expired so that we can pick up the process again.
      await this.db
        .delete(delegatedAccessAccounts)
        .where(eq(delegatedAccessAccounts.delegateUserId, accounts.delegateUserId));
      // Throwing causes this run to fail. The next scheduled run resumes from lastProcessedAccountsId,
      // which points to the user before this one. Since the accounts record is now deleted, this user
      // is skipped and processing continues from where it left off.
      throw tokenExpiredError.error;
    }

    const rateLimitErrors = result.errors.filter(
      (error) => error.reason === CannotReadErrorReason.TransientError,
    );

    // If there are rate limiting errors we rethrow a generic rate limit error because we want
    // retry to continue the batches later.
    if (rateLimitErrors.length > 0) {
      const retryAfterValues = rateLimitErrors
        .map(({ error }) => getRetryAfterMs(error))
        .filter(isNonNullish) as number[];
      throw new GenericRateLimitError(
        `Delegated access sync failed because of rate limiting`,
        retryAfterValues.length > 0 ? Math.max(...retryAfterValues) : null,
        { cause: result.errors },
      );
    }

    throw new Error(`Delegated access sync failed with unhandled errors`, {
      cause: result.errors,
    });
  }

  @Span()
  private async fetchBatch({
    lastProcessedAccountsId,
  }: {
    lastProcessedAccountsId: Nullish<string>;
  }): Promise<{ id: string; delegateUserId: string; ownerUserId: string }[]> {
    return await this.db
      .select({
        id: delegatedAccessAccounts.id,
        delegateUserId: delegatedAccessAccounts.delegateUserId,
        ownerUserId: delegatedAccessAccounts.ownerUserId,
      })
      .from(delegatedAccessAccounts)
      .where(
        and(
          lastProcessedAccountsId
            ? gt(delegatedAccessAccounts.id, lastProcessedAccountsId)
            : undefined,
        ),
      )
      .orderBy(delegatedAccessAccounts.id)
      .limit(50);
  }

  @Span()
  public async decide(): Promise<SyncDelegatedAccessForAllUsersDecision> {
    return this.persistentCacheService.setWith(
      SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
      async ({ currentValue, create, update }): Promise<SyncDelegatedAccessForAllUsersDecision> => {
        if (!currentValue) {
          await create({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedAccountsId: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });

          return { action: 'proceed', lastProcessedAccountsId: null };
        }

        assert.ok(currentValue.dataType === 'DelegatedAccessVerification');

        if (currentValue.payload.state === 'ready') {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedAccountsId: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return { action: 'proceed', lastProcessedAccountsId: null };
        }

        if (currentValue.payload.state === 'failed') {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedAccountsId: currentValue.payload.lastProcessedAccountsId,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedAccountsId: currentValue.payload.lastProcessedAccountsId,
          };
        }

        const currentTime = new Date();
        currentTime.setMinutes(
          currentTime.getMinutes() -
            SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_NO_PROGRESS_THRESHOLD_MINUTES,
        );

        if (currentValue.payload.lastProgressRegisteredAt <= currentTime.getTime()) {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedAccountsId: currentValue.payload.lastProcessedAccountsId,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedAccountsId: currentValue.payload.lastProcessedAccountsId,
          };
        }

        return {
          action: 'skip',
          reason: `Skipped running sync for delegated permissions another sync in progress`,
        };
      },
    );
  }

  private async updateProgressTimestamp(): Promise<void> {
    await this.persistentCacheService.setWith(
      SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
      async ({ currentValue, update }): Promise<void> => {
        assert.ok(currentValue);
        assert.ok(currentValue.dataType === 'DelegatedAccessVerification');
        await update({
          dataType: 'DelegatedAccessVerification',
          payload: {
            ...currentValue.payload,
            lastProgressRegisteredAt: Date.now(),
          },
        });
      },
    );
  }
}
