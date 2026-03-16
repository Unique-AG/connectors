import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GlobalThrottleMiddleware } from '~/msgraph/global-throttle.middleware';
import { extractSafeGraphError } from '~/utils/graph-error.filter';
import { OneNoteDeltaService } from '../onenote-delta.service';
import { OneNoteSyncService } from '../onenote-sync.service';

const StartSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  syncAlreadyRunning: z.boolean().optional(),
  lastSyncedAt: z.string().nullable().optional(),
  secondsSinceLastSync: z.number().nullable().optional(),
  statusNote: z
    .string()
    .optional()
    .describe(
      'Human-readable status information. Always relay this to the user when present — it explains delays, throttling, or background operations.',
    ),
});

@Injectable()
export class StartOneNoteSyncTool {
  private readonly logger = new Logger(StartOneNoteSyncTool.name);

  public constructor(
    private readonly syncService: OneNoteSyncService,
    private readonly deltaService: OneNoteDeltaService,
  ) {}

  @Tool({
    name: 'start_onenote_sync',
    title: 'Start OneNote Sync',
    description:
      'Trigger an immediate incremental OneNote sync for the current user. Only changes since the last sync are fetched.',
    parameters: z.object({}),
    outputSchema: StartSyncOutputSchema,
    annotations: {
      title: 'Start OneNote Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'refresh',
      'unique.app/system-prompt':
        'Use this tool only when the user explicitly asks to sync or refresh their OneNote data. ' +
        'Do not call this tool automatically based on search results or data freshness. Syncs happen automatically in the background.',
      'unique.app/tool-format-information':
        'Always relay the statusNote to the user — it explains what is happening with the sync and whether there are any delays.',
    },
  })
  @Span()
  public async startSync(
    _input: Record<string, never>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof StartSyncOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log({ userProfileId }, 'Tool start_onenote_sync called');

    const deltaStatus = await this.deltaService.getDeltaStatus(userProfileId);
    const lastSyncedAt = deltaStatus?.lastSyncedAt?.toISOString() ?? null;
    const secondsSinceLastSync = deltaStatus?.lastSyncedAt
      ? Math.round((Date.now() - deltaStatus.lastSyncedAt.getTime()) / 1000)
      : null;

    const throttleRemainingMs = GlobalThrottleMiddleware.currentThrottleRemainingMs(userProfileId);
    const throttlePart = throttleRemainingMs > 0
      ? ` Microsoft OneNote is currently rate-limiting requests, so the sync may take longer than usual (~${Math.round(throttleRemainingMs / 1000)}s). This resolves on its own.`
      : '';

    if (this.syncService.isSyncRunning(userProfileId)) {
      return {
        success: true,
        message: 'A sync is already in progress.',
        syncAlreadyRunning: true,
        lastSyncedAt,
        secondsSinceLastSync,
        statusNote: `A sync is already running for your notebooks. Please wait for it to finish before searching for the latest data.${throttlePart}`,
      };
    }

    await this.deltaService.enableSync(userProfileId);

    this.syncService.syncUser(userProfileId).catch((err) => {
      const safeError = extractSafeGraphError(err);
      this.logger.error({ userProfileId, ...safeError }, 'Background sync failed');
    });

    return {
      success: true,
      message: 'Sync started in the background.',
      syncAlreadyRunning: false,
      lastSyncedAt,
      secondsSinceLastSync,
      statusNote: `Sync started in the background. Your OneNote notebooks are being updated — wait a few seconds before searching for the latest data.${throttlePart}`,
    };
  }
}
