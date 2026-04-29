import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, gt } from 'drizzle-orm';
import { last } from 'remeda';
import { DRIZZLE, DrizzleDatabase, delegatedAccessPipelines } from '~/db';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { Nullish } from '~/utils/nullish';
import { SyncDelegatedAccessCommand } from './sync-delegated-access.command';

const CACHE_KEY = `SyncDelegatedAccessForAllUsers`;

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

  public async run(): Promise<void> {
    const decision = await this.decide();
    if (decision.action === 'skip') {
      this.logger.log({ msg: `Skipped running sync delegated access. Reason: ${decision.reason}` });
      return;
    }

    let lastProcessedPipelineId: Nullish<string> = decision.lastProcessedPipelineId;
    let batch = await this.fetchBatch({ lastProcessedPipelineId });

    while (batch.length) {
      await Promise.all(
        batch.map((pipeline) => this.syncDelegatedAccessCommand.run({ pipelineId: pipeline.id })),
      );
      lastProcessedPipelineId = last(batch)?.id;
      await this.persistentCacheService.setWith(
        CACHE_KEY,
        async ({ currentValue, update }): Promise<void> => {
          assert.ok(currentValue);
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
      batch = await this.fetchBatch({ lastProcessedPipelineId });
    }
  }

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
      // We process at most 5 pipelines in pharalel
      .limit(5);
  }

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
        currentTime.setMinutes(currentTime.getMinutes() - 10);

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
