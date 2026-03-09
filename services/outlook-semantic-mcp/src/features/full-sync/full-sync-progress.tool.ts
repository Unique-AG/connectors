import { IngestionState, type UniqueApiClient } from '@unique-ag/unique-api';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, inboxConfiguration, userProfiles } from '~/db';
import { getRootScopePathForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';

const InputSchema = z.object({});

const IngestionStateEnum = z.nativeEnum(IngestionState);

// When inbox is not connected, only `message` is populated and configuration fields are null.
const OutputSchema = z.object({
  message: z.string().nullable(),
  id: z.string().nullable(),
  userProfileId: z.string().nullable(),
  syncState: z.enum(['idle', 'running', 'failed']).nullable(),
  lastFullSyncRunAt: z.string().nullable(),
  syncStartedAt: z.string().nullable(),
  messagesFromMicrosoft: z.number().nullable(),
  messagesQueuedForSync: z.number().nullable(),
  messagesProcessed: z.number().nullable(),
  filters: z.unknown(),
  createdAt: z.string().nullable(),
  updatedAt: z.string().nullable(),
  ingestionStats: z.record(IngestionStateEnum, z.number().optional()).optional(),
  statsUnavailable: z.literal(true).optional(),
});

@Injectable()
export class FullSyncProgressTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Tool({
    name: 'full_sync_progress',
    title: 'Full Sync Progress',
    description:
      'Check the current progress of the full email sync. Returns inbox configuration details and ingestion statistics from the knowledge base.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Full Sync Progress',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'status',
      'unique.app/system-prompt':
        'Returns the current full sync progress including inbox configuration and ingestion statistics. Use this to monitor how many emails have been processed and their ingestion states.',
    },
  })
  @Span()
  public async fullSyncProgress(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.debug({ userProfileId, msg: 'Fetching full sync progress for user' });

    const config = await this.db.query.inboxConfiguration.findFirst({
      where: eq(inboxConfiguration.userProfileId, userProfileId),
    });

    if (!config) {
      this.logger.debug({ userProfileId, msg: 'No inbox configuration found for user' });
      return {
        message: 'Inbox not connected — use `connect_inbox` first.',
        id: null,
        userProfileId: null,
        syncState: null,
        lastFullSyncRunAt: null,
        syncStartedAt: null,
        messagesFromMicrosoft: null,
        messagesQueuedForSync: null,
        messagesProcessed: null,
        filters: null,
        createdAt: null,
        updatedAt: null,
      };
    }

    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });

    const configFields = {
      message: null,
      id: config.id,
      userProfileId: config.userProfileId,
      syncState: config.syncState,
      lastFullSyncRunAt: config.lastFullSyncRunAt?.toISOString() ?? null,
      syncStartedAt: config.syncStartedAt?.toISOString() ?? null,
      messagesFromMicrosoft: config.messagesFromMicrosoft,
      messagesQueuedForSync: config.messagesQueuedForSync,
      messagesProcessed: config.messagesProcessed,
      filters: config.filters,
      createdAt: config.createdAt.toISOString(),
      updatedAt: config.updatedAt.toISOString(),
    };

    if (!userProfile?.email) {
      this.logger.warn({ userProfileId, msg: 'User profile email missing, cannot fetch ingestion stats' });
      return { ...configFields, statsUnavailable: true as const };
    }

    try {
      const rootScopePath = getRootScopePathForUser(userProfile.email);
      const ingestionStats = await this.uniqueApi.content.getIngestionStats(rootScopePath);

      this.logger.debug({ userProfileId, msg: 'Full sync progress retrieved' });

      return { ...configFields, ingestionStats };
    } catch (error) {
      this.logger.warn({
        userProfileId,
        msg: 'Failed to fetch ingestion stats from Unique API',
        error,
      });
      return { ...configFields, statsUnavailable: true as const };
    }
  }
}
