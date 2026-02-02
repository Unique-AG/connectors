import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2, OnEvent } from '@nestjs/event-emitter';
import { Cron, CronExpression } from '@nestjs/schedule';
import { and, eq, isNotNull, isNull, lt } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { DRIZZLE, DrizzleDatabase } from '../../drizzle';
import { EmailDeltaSyncRequestedEvent, EmailEvents } from './email.events';

@Injectable()
export class EmailSyncSchedulerService {
  private readonly logger = new Logger(EmailSyncSchedulerService.name);
  private readonly MAX_RETRY_HOURS = 24; // Maximum hours to retry a failed sync
  private readonly syncInProgress = new Set<string>();

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  /**
   * Periodic check for folders that need syncing as a safeguard against failing subscription events.
   */
  @Cron(CronExpression.EVERY_5_MINUTES)
  public async checkFoldersForSync() {
    this.logger.debug('Checking folders for sync');

    try {
      // Find folders that are activated, have a sync token (not initial sync),
      // and either haven't been synced recently or have never been synced
      const cutoffTime = new Date();
      cutoffTime.setMinutes(cutoffTime.getMinutes() - 30); // Sync if not synced in last 30 minutes

      const foldersToSync = await this.db.query.folders.findMany({
        where: and(
          isNotNull(foldersTable.activatedAt),
          isNull(foldersTable.deactivatedAt),
          isNotNull(foldersTable.syncToken),
          lt(foldersTable.lastSyncedAt, cutoffTime.toISOString()),
        ),
        limit: 10, // Process up to 10 folders at a time
      });

      for (const folder of foldersToSync) {
        // Skip if already syncing
        if (this.syncInProgress.has(folder.id)) {
          this.logger.debug({
            msg: 'Folder sync already in progress, skipping',
            folderId: folder.id,
          });
          continue;
        }

        this.logger.log({
          msg: 'Triggering scheduled sync for folder',
          folderId: folder.id,
          folderName: folder.name,
          lastSyncedAt: folder.lastSyncedAt,
        });

        this.syncInProgress.add(folder.id);

        // Emit delta sync request
        this.eventEmitter.emit(
          EmailEvents.EmailDeltaSyncRequested,
          new EmailDeltaSyncRequestedEvent(
            TypeID.fromString(folder.userProfileId, 'user_profile'),
            folder.id,
          ),
        );
      }
    } catch (error) {
      this.logger.error({
        msg: 'Failed to check folders for sync',
        error: serializeError(normalizeError(error)),
      });
    }
  }

  /**
   * Clean up sync status when sync completes
   */
  @OnEvent(EmailEvents.EmailSyncCompleted)
  public onSyncCompleted(event: { folderId: string }) {
    this.syncInProgress.delete(event.folderId);
    this.logger.debug({
      msg: 'Folder sync completed, removing from in-progress set',
      folderId: event.folderId,
    });
  }

  /**
   * Handle sync failures and schedule retries
   */
  @OnEvent(EmailEvents.EmailSyncFailed)
  public async onSyncFailed(event: { folderId: string; error: Error }) {
    this.syncInProgress.delete(event.folderId);

    this.logger.warn({
      msg: 'Folder sync failed, will retry in next scheduled check',
      folderId: event.folderId,
      error: serializeError(event.error),
    });

    // Update last sync attempt time to prevent immediate retry
    const retryTime = new Date();
    retryTime.setMinutes(retryTime.getMinutes() + 5); // Wait at least 5 minutes before retry

    await this.db
      .update(foldersTable)
      .set({
        lastSyncedAt: retryTime.toISOString(),
      })
      .where(eq(foldersTable.id, event.folderId));
  }

  /**
   * Retry folders with no sync token (initial sync failures)
   * Runs every hour
   */
  @Cron(CronExpression.EVERY_HOUR)
  public async retryInitialSyncs() {
    this.logger.debug('Checking for folders needing initial sync retry');

    try {
      const foldersNeedingInitialSync = await this.db.query.folders.findMany({
        where: and(
          isNotNull(foldersTable.activatedAt),
          isNull(foldersTable.deactivatedAt),
          isNull(foldersTable.syncToken),
        ),
        limit: 5, // Process up to 5 folders at a time
      });

      for (const folder of foldersNeedingInitialSync) {
        if (this.syncInProgress.has(folder.id)) {
          continue;
        }

        // Check if folder was activated more than MAX_RETRY_HOURS ago
        const activatedDate = new Date(folder.activatedAt as string);
        const hoursSinceActivation = (Date.now() - activatedDate.getTime()) / (1000 * 60 * 60);

        if (hoursSinceActivation > this.MAX_RETRY_HOURS) {
          this.logger.warn({
            msg: 'Folder initial sync exceeded max retry time, skipping',
            folderId: folder.id,
            folderName: folder.name,
            activatedAt: folder.activatedAt,
          });
          continue;
        }

        this.logger.log({
          msg: 'Retrying initial sync for folder',
          folderId: folder.id,
          folderName: folder.name,
        });

        this.syncInProgress.add(folder.id);

        // Emit delta sync request (will trigger initial sync since no token exists)
        this.eventEmitter.emit(
          EmailEvents.EmailDeltaSyncRequested,
          new EmailDeltaSyncRequestedEvent(
            TypeID.fromString(folder.userProfileId, 'user_profile'),
            folder.id,
          ),
        );
      }
    } catch (error) {
      this.logger.error({
        msg: 'Failed to retry initial syncs',
        error: serializeError(normalizeError(error)),
      });
    }
  }
}
