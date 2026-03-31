import { GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { asc, eq, sql } from 'drizzle-orm';
import Bottleneck from 'bottleneck';
import { Span } from 'nestjs-otel';
import { errors } from 'undici';
import { DRIZZLE, DrizzleDatabase, directories, directoriesSync } from '~/db';
import { traceAttrs } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import z from 'zod/v4';

const folderMovementMessagePageSchema = z.object({
  value: z.array(z.object({ id: z.string() })),
  '@odata.nextLink': z.string().optional(),
});
import { IngestEmailCommand } from '../mail-ingestion/ingest-email.command';
import { isWithinCooldown } from '~/utils/is-within-cooldown';

export const FOLDER_MOVEMENT_SYNC_RUNNING_HEARTBEAT_MINUTES = 20;
export const FOLDER_MOVEMENT_SYNC_FAILED_RETRY_MINUTES = 20;

export type FolderMovementSyncResult = 'completed' | 'skipped' | 'failed';

@Injectable()
export class FolderMovementSyncCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly ingestEmailCommand: IngestEmailCommand,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<FolderMovementSyncResult> {
    traceAttrs({ userProfileId });
    this.logger.log({ userProfileId, msg: 'Folder movement sync triggered' });

    const lockResult = await this.acquireLock(userProfileId);
    if (lockResult.status === 'skip') {
      return 'skipped';
    }

    try {
      await this.processMarkedFolders(userProfileId);

      await this.db
        .update(directoriesSync)
        .set({
          folderMovementSyncState: 'ready',
          folderMovementSyncHeartbeatAt: sql`NOW()`,
        })
        .where(eq(directoriesSync.userProfileId, userProfileId))
        .execute();

      this.logger.log({ userProfileId, msg: 'Folder movement sync completed' });
      return 'completed';
    } catch (error) {
      const isRateLimit =
        (error instanceof GraphError && error.statusCode === 429) ||
        (error instanceof errors.ResponseError && error.statusCode === 429) ||
        error instanceof Bottleneck.BottleneckError;

      if (isRateLimit) {
        throw error;
      }

      this.logger.error({ err: error, userProfileId, msg: 'Folder movement sync failed' });
      await this.db
        .update(directoriesSync)
        .set({ folderMovementSyncState: 'failed' })
        .where(eq(directoriesSync.userProfileId, userProfileId))
        .execute();
      return 'failed';
    }
  }

  private async acquireLock(
    userProfileId: string,
  ): Promise<{ status: 'proceed' } | { status: 'skip' }> {
    return this.db.transaction(async (tx) => {
      const row = await tx
        .select({
          folderMovementSyncState: directoriesSync.folderMovementSyncState,
          folderMovementSyncHeartbeatAt: directoriesSync.folderMovementSyncHeartbeatAt,
        })
        .from(directoriesSync)
        .where(eq(directoriesSync.userProfileId, userProfileId))
        .for('update')
        .then((rows) => rows[0]);

      if (!row) {
        this.logger.warn({ userProfileId, msg: 'No directoriesSync row found, skipping' });
        return { status: 'skip' as const };
      }

      if (
        row.folderMovementSyncState === 'running' &&
        isWithinCooldown(
          row.folderMovementSyncHeartbeatAt,
          FOLDER_MOVEMENT_SYNC_RUNNING_HEARTBEAT_MINUTES,
        )
      ) {
        this.logger.log({ userProfileId, msg: 'Folder movement sync already running, skipping' });
        return { status: 'skip' as const };
      }

      await tx
        .update(directoriesSync)
        .set({
          folderMovementSyncState: 'running',
          folderMovementSyncHeartbeatAt: sql`NOW()`,
        })
        .where(eq(directoriesSync.userProfileId, userProfileId))
        .execute();

      return { status: 'proceed' as const };
    });
  }

  private async processMarkedFolders(userProfileId: string): Promise<void> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    let totalProcessed = 0;

    while (true) {
      const folder = await this.db
        .select({
          id: directories.id,
          providerDirectoryId: directories.providerDirectoryId,
          directoryMovementResyncCursor: directories.directoryMovementResyncCursor,
        })
        .from(directories)
        .where(
          sql`${directories.userProfileId} = ${userProfileId} AND ${directories.parentChangeDetectedAt} IS NOT NULL`,
        )
        .orderBy(asc(directories.parentChangeDetectedAt))
        .limit(1)
        .then((rows) => rows[0]);

      if (!folder) {
        break;
      }

      const { id: directoryId, providerDirectoryId, directoryMovementResyncCursor } = folder;

      let raw: unknown;
      if (directoryMovementResyncCursor) {
        raw = await client.api(directoryMovementResyncCursor).get();
      } else {
        raw = await client
          .api(`me/mailFolders/${providerDirectoryId}/messages`)
          .header('Prefer', 'IdType="ImmutableId"')
          .select('id')
          .top(100)
          .orderby('id')
          .get();
      }

      const response = folderMovementMessagePageSchema.parse(raw);

      for (const email of response.value) {
        const result = await this.ingestEmailCommand.run({ userProfileId, messageId: email.id });
        if (result === 'failed') {
          this.logger.warn({
            userProfileId,
            messageId: email.id,
            directoryId,
            msg: 'Email ingestion failed during folder movement sync, continuing',
          });
        }
        totalProcessed++;
      }

      if (!response['@odata.nextLink']) {
        await this.db
          .update(directories)
          .set({
            parentChangeDetectedAt: null,
            directoryMovementResyncCursor: null,
          })
          .where(eq(directories.id, directoryId))
          .execute();
      } else {
        await this.db
          .update(directories)
          .set({ directoryMovementResyncCursor: response['@odata.nextLink'] })
          .where(eq(directories.id, directoryId))
          .execute();

        if (totalProcessed >= 100) {
          break;
        }
      }
    }
  }
}
