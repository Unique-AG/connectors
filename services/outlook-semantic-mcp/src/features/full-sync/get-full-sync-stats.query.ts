import { IngestionState, UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import z from 'zod';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { getRootScopePathForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';

const IngestionStateEnum = z.nativeEnum(IngestionState);

export const GetFullSyncStatsResponse = z.object({
  syncStats: z
    .object({
      state: z.enum(['idle', 'running', 'failed']).nullable(),
      runAt: z.string().nullable(),
      startedAt: z.string().nullable(),
      messages: z.object({
        received: z.number().nullable(),
        queuedForSync: z.number().nullable(),
        processed: z.number().nullable(),
      }),
    })
    .nullable(),
  ingestionStats: z.partialRecord(IngestionStateEnum, z.number().optional()).nullable(),
});

type FullSyncStats = z.infer<typeof GetFullSyncStatsResponse>;

@Injectable()
export class GetFullSyncStatsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<FullSyncStats> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const config = await this.db.query.inboxConfiguration.findFirst({
      where: eq(inboxConfiguration.userProfileId, userProfile.id),
    });

    if (!config) {
      this.logger.debug({ userProfileId, msg: 'No inbox configuration found for user' });
      return {
        syncStats: null,
        ingestionStats: null,
      };
    }

    const configFields: Omit<FullSyncStats, 'message'> = {
      syncStats: {
        state: config.syncState,
        runAt: config.lastFullSyncRunAt?.toISOString() ?? null,
        startedAt: config.syncStartedAt?.toISOString() ?? null,
        messages: {
          received: config.messagesFromMicrosoft,
          queuedForSync: config.messagesQueuedForSync,
          processed: config.messagesProcessed,
        },
      },
      ingestionStats: null,
    };

    try {
      const rootScopePath = getRootScopePathForUser(userProfile.providerUserId);
      const ingestionStats = await this.uniqueApi.content.getIngestionStats(rootScopePath);

      this.logger.debug({ userProfileId, msg: 'Full sync progress retrieved' });

      return { ...configFields, ingestionStats };
    } catch (error) {
      this.logger.warn({
        userProfileId,
        msg: 'Failed to fetch ingestion stats from Unique API',
        error,
      });
      return configFields;
    }
  }
}
