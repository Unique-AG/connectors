import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, isNotNull, isNull, lt, or } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, directories, directoriesSync } from '~/db';
import { getThreshold } from '~/utils/get-threshold';
import {
  FOLDER_MOVEMENT_SYNC_FAILED_RETRY_MINUTES,
  FOLDER_MOVEMENT_SYNC_RUNNING_HEARTBEAT_MINUTES,
} from './folder-movement-sync.command';
import { FolderMovementSyncEventDto } from './folder-movement-sync-event.dto';

const FOLDER_MOVEMENT_SYNC_CRON_SCHEDULE = '*/5 * * * *';

@Injectable()
export class FolderMovementSyncSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    this.logger.log({ msg: 'FolderMovementSyncSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('folder-movement-sync');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping folder-movement-sync cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(FOLDER_MOVEMENT_SYNC_CRON_SCHEDULE, async () => {
      try {
        await this.triggerFolderMovementSync();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during folder movement sync scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('folder-movement-sync', job);
    job.start();
  }

  public async triggerFolderMovementSync(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping folder movement sync scan due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'Folder movement sync scan triggered' });

    const markedUsers = await this.db
      .selectDistinct({ userProfileId: directories.userProfileId })
      .from(directories)
      .where(isNotNull(directories.parentChangeDetectedAt));

    const staleUsers = await this.db
      .selectDistinct({ userProfileId: directoriesSync.userProfileId })
      .from(directoriesSync)
      .where(
        or(
          and(
            eq(directoriesSync.folderMovementSyncState, 'failed'),
            or(
              isNull(directoriesSync.folderMovementSyncHeartbeatAt),
              lt(
                directoriesSync.folderMovementSyncHeartbeatAt,
                getThreshold(FOLDER_MOVEMENT_SYNC_FAILED_RETRY_MINUTES),
              ),
            ),
          ),
          and(
            eq(directoriesSync.folderMovementSyncState, 'running'),
            or(
              isNull(directoriesSync.folderMovementSyncHeartbeatAt),
              lt(
                directoriesSync.folderMovementSyncHeartbeatAt,
                getThreshold(FOLDER_MOVEMENT_SYNC_RUNNING_HEARTBEAT_MINUTES),
              ),
            ),
          ),
        ),
      );

    const userIds = [
      ...new Set([
        ...markedUsers.map((r) => r.userProfileId),
        ...staleUsers.map((r) => r.userProfileId),
      ]),
    ];

    if (userIds.length === 0) {
      return;
    }

    this.logger.log({
      msg: 'Publishing folder movement sync events',
      count: userIds.length,
    });

    for (const userProfileId of userIds) {
      const event = FolderMovementSyncEventDto.parse({
        type: 'unique.outlook-semantic-mcp.sync.folder-movement',
        payload: { userProfileId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }
}
