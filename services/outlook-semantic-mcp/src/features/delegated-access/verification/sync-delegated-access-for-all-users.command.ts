import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, gt } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, delegatedAccessAccounts } from '~/db';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { Nullish } from '~/utils/nullish';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';
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
  ) {}

  @Span()
  public async run(): Promise<void> {
    const decision = await this.decide();
    if (decision.action === 'skip') {
      this.logger.log({ msg: `Skipped running sync delegated access. Reason: ${decision.reason}` });
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
          fn: async () => {
            await this.syncDelegatedAccessCommand.run({ accountsId: accounts.id });
            return { status: 'success' };
          },
          onError: rethrowRateLimitError,
          getResultFailure: (error) => ({ status: 'failed', error }),
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

  @Span()
  private async fetchBatch({
    lastProcessedAccountsId,
  }: {
    lastProcessedAccountsId: Nullish<string>;
  }): Promise<{ id: string }[]> {
    return await this.db
      .select({ id: delegatedAccessAccounts.id })
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
}
