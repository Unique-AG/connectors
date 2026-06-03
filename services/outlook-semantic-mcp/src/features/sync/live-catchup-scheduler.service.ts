import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, exists, inArray, lt, not, or, sql } from 'drizzle-orm';
import z from 'zod';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { IngestionConfig, ingestionConfig, McpBackendType } from '~/config';
import {
  delegatedAccessAccounts,
  DRIZZLE,
  DrizzleDatabase,
  inboxConfigurations,
  userProfiles,
} from '~/db';
import { NewTrace, traceEvent } from '~/features/tracing.utils';
import { getThreshold } from '~/utils/get-threshold';
import {
  FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES,
  READY_LIVE_CATCHUP_THRESHOLD_MINUTES,
  RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES,
} from './live-catch-up/live-catch-up.command';
import { LiveCatchUpEventDto } from './live-catch-up/live-catch-up-event.dto';
import { selectUserProfileIdsWhichCanRunTheSyncProcess } from './sync-scheduler.utils';

@Injectable()
export class LiveCatchupSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(ingestionConfig.KEY) private readonly config: IngestionConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    if (this.config.mcpBackend !== McpBackendType.MicrosoftGraphAndUniqueApi) {
      return;
    }

    this.logger.log({ msg: 'LiveCatchupSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    for (const name of ['live-catchup-recovery', 'live-catchup-recheck']) {
      try {
        this.schedulerRegistry.getCronJob(name).stop();
      } catch (err) {
        this.logger.error({ msg: `Error stopping ${name} cron job`, err });
      }
    }
  }

  private setupCronJob(): void {
    if (this.config.mcpBackend !== McpBackendType.MicrosoftGraphAndUniqueApi) {
      return;
    }

    const recoveryJob = new CronJob(this.config.liveCatchupRecoveryCron, () => {
      this.runRecoveryScan();
    });
    this.schedulerRegistry.addCronJob('live-catchup-recovery', recoveryJob);
    recoveryJob.start();

    const recheckJob = new CronJob(this.config.liveCatchupRecheckCron, () => {
      this.runReadyLiveCatchupsWhichDidNotRunRecently();
    });
    this.schedulerRegistry.addCronJob('live-catchup-recheck', recheckJob);
    recheckJob.start();
  }

  @NewTrace('cron.live-catchup-recovery')
  public async runRecoveryScan(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({
        msg: 'Skipping live catchup recovery scan due to shutdown',
      });
      return;
    }

    try {
      this.logger.log({ msg: 'Live catchup recovery scan triggered' });

      await this.recoverStuckLiveCatchUps();
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during live catchup recovery scan',
        err,
      });
    }
  }

  @NewTrace('cron.live-catchup-ready-recheck')
  public async runReadyLiveCatchupsWhichDidNotRunRecently(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({
        msg: 'Skipping live catchup recovery scan due to shutdown',
      });
      return;
    }

    try {
      this.logger.log({ msg: 'Live catchup recovery scan triggered' });
      await this.rerunReadyLiveCatchupsWhichDidNotRunRecently();
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during live catchup recovery scan',
        err,
      });
    }
  }

  private async recoverStuckLiveCatchUps(): Promise<void> {
    const stuckConfigs = await this.db
      .select({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .where(
        and(
          inArray(
            inboxConfigurations.userProfileId,
            selectUserProfileIdsWhichCanRunTheSyncProcess(this.db),
          ),
          or(
            and(
              eq(inboxConfigurations.liveCatchUpState, 'failed'),
              lt(
                inboxConfigurations.liveCatchUpHeartbeatAt,
                getThreshold(FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES),
              ),
            ),
            and(
              eq(inboxConfigurations.liveCatchUpState, 'running'),
              lt(
                inboxConfigurations.liveCatchUpHeartbeatAt,
                getThreshold(RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES),
              ),
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    await this.rerunLiveCatchups(
      stuckConfigs.map(({ userProfileId }) =>
        LiveCatchUpEventDto.parse({
          type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
          payload: { userProfileId },
        }),
      ),
    );

    await this.logSharedMailboxesWithNoDelegates();
  }

  private async rerunReadyLiveCatchupsWhichDidNotRunRecently(): Promise<void> {
    const stuckConfigs = await this.db
      .select({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .where(
        and(
          inArray(
            inboxConfigurations.userProfileId,
            selectUserProfileIdsWhichCanRunTheSyncProcess(this.db),
          ),
          and(
            eq(inboxConfigurations.liveCatchUpState, 'ready'),
            lt(
              inboxConfigurations.liveCatchUpHeartbeatAt,
              getThreshold(READY_LIVE_CATCHUP_THRESHOLD_MINUTES),
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    await this.rerunLiveCatchups(
      stuckConfigs.map(({ userProfileId }) =>
        LiveCatchUpEventDto.parse({
          type: 'unique.outlook-semantic-mcp.live-catch-up.ready-recheck',
          payload: { userProfileId },
        }),
      ),
    );

    await this.logSharedMailboxesWithNoDelegates();
  }

  private async rerunLiveCatchups(events: z.infer<typeof LiveCatchUpEventDto>[]): Promise<void> {
    if (!events.length) {
      this.logger.log({
        msg: 'No live catch-ups which did not run for a long time',
      });
      return;
    }

    traceEvent('live-catch-up stuck recovery triggered', {
      count: events.length,
      userProfileIds: events.map((event) => event.payload.userProfileId ?? null),
    });

    this.logger.log({
      msg: 'Found ready live catch-up configurations',
      count: events.length,
    });

    for (const event of events) {
      this.logger.log({
        msg: `Publishing live catch-up: ${event.type}`,
        userProfileId: event.payload.userProfileId ?? null,
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }

  private async logSharedMailboxesWithNoDelegates(): Promise<void> {
    const configs = await this.db
      .select({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .innerJoin(userProfiles, eq(userProfiles.id, inboxConfigurations.userProfileId))
      .where(
        and(
          eq(userProfiles.source, 'shared-mailbox'),
          not(
            exists(
              this.db
                .select({ one: sql`1` })
                .from(delegatedAccessAccounts)
                .where(eq(delegatedAccessAccounts.ownerUserId, inboxConfigurations.userProfileId)),
            ),
          ),
        ),
      );
    for (const { userProfileId } of configs) {
      this.logger.warn({ userProfileId, msg: 'Shared-mailbox inbox config has no delegates' });
    }
  }
}
