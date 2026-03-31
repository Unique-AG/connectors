import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, asc, eq, isNotNull, SQL, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import z from 'zod/v4';
import { DRIZZLE, DrizzleDatabase, directories, directoriesSync, inboxConfigurations } from '~/db';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceAttrs } from '~/features/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { isWithinCooldown } from '~/utils/is-within-cooldown';
import { IngestEmailCommand } from '../mail-ingestion/ingest-email.command';

const folderMovementMessagePageSchema = z.object({
  value: z.array(z.object({ id: z.string() })),
  '@odata.nextLink': z.string().optional(),
});

export const FOLDER_MOVEMENT_SYNC_RUNNING_HEARTBEAT_MINUTES = 20;
export const FOLDER_MOVEMENT_SYNC_FAILED_RETRY_MINUTES = 20;

export type FolderMovementSyncResult = 'completed' | 'skipped' | 'failed';

type DirectorySyncSelect = typeof directoriesSync.$inferSelect;

export type DirectorySyncUpdate = Partial<{
  [K in Exclude<keyof DirectorySyncSelect, 'userProfileId'>]: DirectorySyncSelect[K] | SQL<unknown>;
}>;

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

      await this.updateDirectorySyncByUserProfile(userProfileId, {
        folderMovementSyncState: 'ready',
        folderMovementSyncHeartbeatAt: sql`NOW()`,
      });
      this.logger.log({ userProfileId, msg: 'Folder movement sync completed' });
      return 'completed';
    } catch (error) {
      this.logger.error({ err: error, userProfileId, msg: 'Folder movement sync failed' });
      await this.updateDirectorySyncByUserProfile(userProfileId, {
        folderMovementSyncState: 'failed',
        folderMovementSyncHeartbeatAt: sql`NOW()`,
      });
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
      const row = await this.db
        .select({
          directoryId: directories.id,
          providerDirectoryId: directories.providerDirectoryId,
          directoryMovementResyncCursor: directories.directoryMovementResyncCursor,
          filters: inboxConfigurations.filters,
        })
        .from(directories)
        .innerJoin(
          inboxConfigurations,
          eq(inboxConfigurations.userProfileId, directories.userProfileId),
        )
        .where(
          and(
            eq(directories.userProfileId, userProfileId),
            isNotNull(directories.parentChangeDetectedAt),
          ),
        )
        .orderBy(asc(directories.parentChangeDetectedAt))
        .limit(1)
        .then((rows) => rows[0]);

      if (!row) {
        return;
      }
      const filters = inboxConfigurationMailFilters.parse(row.filters);
      const { directoryId, providerDirectoryId, directoryMovementResyncCursor } = row;

      const response = await this.fetchPage({
        client,
        userProfileId,
        directoryId,
        providerDirectoryId,
        ignoredBefore: filters.ignoredBefore,
        nextLink: directoryMovementResyncCursor,
      });

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

        await this.updateDirectorySyncByUserProfile(userProfileId, {
          folderMovementSyncHeartbeatAt: sql`NOW()`,
        });

        if (result === 'failed' || result === 'ingested') {
          totalProcessed++;
        }
      }
      const fieldsToUpdate = {
        // This field is optional
        parentChangeDetectedAt: null as null | undefined,
        directoryMovementResyncCursor: response['@odata.nextLink'] ?? null,
      };
      if (!isNullish(fieldsToUpdate.directoryMovementResyncCursor)) {
        delete fieldsToUpdate.parentChangeDetectedAt;
      }

      await this.db
        .update(directories)
        .set(fieldsToUpdate)
        .where(eq(directories.id, directoryId))
        .execute();

      if (totalProcessed >= 100) {
        return;
      }
    }
  }

  private async fetchPage({
    client,
    ignoredBefore,
    providerDirectoryId,
    userProfileId,
    directoryId,
    nextLink,
  }: {
    nextLink: string | null;
    client: Client;
    providerDirectoryId: string;
    userProfileId: string;
    directoryId: string;
    ignoredBefore: Date;
  }) {
    let raw: unknown;
    if (!nextLink) {
      raw = await this.fetchFirstPage(client, {
        providerDirectoryId,
        ignoredBefore: ignoredBefore,
      });
      return folderMovementMessagePageSchema.parse(raw);
    }

    try {
      raw = await client.api(nextLink).get();
      return folderMovementMessagePageSchema.parse(raw);
    } catch (error) {
      if (!(error instanceof GraphError && error.statusCode === 410)) {
        throw error;
      }
      this.logger.warn({
        userProfileId,
        directoryId,
        msg: 'Graph API cursor expired (410), restarting folder from first page',
      });
      raw = await this.fetchFirstPage(client, {
        providerDirectoryId,
        ignoredBefore,
      });
      return folderMovementMessagePageSchema.parse(raw);
    }
  }

  private async fetchFirstPage(
    client: Client,
    { ignoredBefore, providerDirectoryId }: { providerDirectoryId: string; ignoredBefore: Date },
  ): Promise<unknown> {
    return client
      .api(`me/mailFolders/${providerDirectoryId}/messages`)
      .header('Prefer', 'IdType="ImmutableId"')
      .select('id')
      .filter(`createdDateTime ge ${ignoredBefore.toISOString()}`)
      .orderby('createdDateTime desc')
      .top(100)
      .get();
  }

  private async updateDirectorySyncByUserProfile(
    userProfileId: string,
    data: DirectorySyncUpdate,
  ): Promise<void> {
    await this.db
      .update(directoriesSync)
      .set(data)
      .where(eq(directoriesSync.userProfileId, userProfileId))
      .execute();
  }
}
