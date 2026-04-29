import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, gt } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, delegatedAccessPipelines } from '~/db';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { Nullish } from '~/utils/nullish';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';
import { SyncDelegatedAccessCommand } from './sync-delegated-access.command';

const CACHE_KEY = `SyncDelegatedAccessForAllUsers`;
const NO_PROGRESS_REGISTERED_THRESHOLD_IN_MINUTES = 10;

type SyncDelegatedAccessForAllUsersDecision =
  | { action: 'proceed'; lastProcessedPipelineId: Nullish<string> }
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
      await this.runSyncInBatches(decision.lastProcessedPipelineId);
      finalState = 'ready';
    } catch (error) {
      this.logger.error({ msg: `Failed to run delegated access sync`, err: error });
      finalState = 'failed';
    }
    await this.persistentCacheService.setWith(
      CACHE_KEY,
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
  private async runSyncInBatches(lastProcessedPipelineId: Nullish<string>): Promise<void> {
    let batch = await this.fetchBatch({ lastProcessedPipelineId });

    while (batch.length) {
      this.logger.log({
        msg: `Running delegated access sync for batch: ${batch.length}`,
        pipelineIds: batch.map((item) => item.id).join(', '),
      });
      for (const pipeline of batch) {
        await withRetryAttempts({
          fn: async () => {
            await this.syncDelegatedAccessCommand.run({ pipelineId: pipeline.id });
            return { status: 'success' };
          },
          onError: rethrowRateLimitError,
          getResultFailure: (error) => ({ status: 'failed', error }),
        });
        lastProcessedPipelineId = pipeline.id;
        await this.persistentCacheService.setWith(
          CACHE_KEY,
          async ({ currentValue, update }): Promise<void> => {
            assert.ok(currentValue);
            assert.ok(currentValue.dataType === 'DelegatedAccessVerification');
            await update({
              dataType: 'DelegatedAccessVerification',
              payload: {
                ...currentValue.payload,
                lastProcessedPipelineId: lastProcessedPipelineId,
                lastProgressRegisteredAt: Date.now(),
              },
            });
          },
        );
      }

      batch = await this.fetchBatch({ lastProcessedPipelineId });
    }
  }

  @Span()
  private async fetchBatch({
    lastProcessedPipelineId,
  }: {
    lastProcessedPipelineId: Nullish<string>;
  }): Promise<{ id: string }[]> {
    return await this.db
      .select({ id: delegatedAccessPipelines.id })
      .from(delegatedAccessPipelines)
      .where(
        and(
          lastProcessedPipelineId
            ? gt(delegatedAccessPipelines.id, lastProcessedPipelineId)
            : undefined,
        ),
      )
      .orderBy(delegatedAccessPipelines.id)
      .limit(50);
  }

  @Span()
  public async decide(): Promise<SyncDelegatedAccessForAllUsersDecision> {
    return this.persistentCacheService.setWith(
      CACHE_KEY,
      async ({ currentValue, create, update }): Promise<SyncDelegatedAccessForAllUsersDecision> => {
        if (!currentValue) {
          await create({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedPipelineId: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });

          return { action: 'proceed', lastProcessedPipelineId: null };
        }

        assert.ok(currentValue.dataType === 'DelegatedAccessVerification');

        if (currentValue.payload.state === 'ready') {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedPipelineId: null,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return { action: 'proceed', lastProcessedPipelineId: null };
        }

        if (currentValue.payload.state === 'failed') {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedPipelineId: currentValue.payload.lastProcessedPipelineId,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedPipelineId: currentValue.payload.lastProcessedPipelineId,
          };
        }

        const currentTime = new Date();
        currentTime.setMinutes(
          currentTime.getMinutes() - NO_PROGRESS_REGISTERED_THRESHOLD_IN_MINUTES,
        );

        if (currentValue.payload.lastProgressRegisteredAt <= currentTime.getTime()) {
          await update({
            dataType: 'DelegatedAccessVerification',
            payload: {
              state: 'running',
              lastProcessedPipelineId: currentValue.payload.lastProcessedPipelineId,
              lastProgressRegisteredAt: Date.now(),
            },
          });
          return {
            action: 'proceed',
            lastProcessedPipelineId: currentValue.payload.lastProcessedPipelineId,
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
