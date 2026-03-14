import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GlobalThrottleMiddleware } from '~/msgraph/global-throttle.middleware';
import { OneNoteDeltaService } from '../onenote-delta.service';
import { OneNoteSyncService } from '../onenote-sync.service';

const VerifySyncStatusOutputSchema = z.object({
  status: z.enum(['active', 'inactive', 'disabled', 'error']),
  message: z.string(),
  lastSyncedAt: z.string().optional(),
  lastSyncStatus: z.string().optional(),
  isSyncRunning: z.boolean().describe('Whether a sync is currently in progress'),
  statusNote: z
    .string()
    .describe(
      'Human-readable status summary. Always relay this to the user — it explains the current state of their OneNote sync.',
    ),
});

@Injectable()
export class VerifyOneNoteSyncStatusTool {
  private readonly logger = new Logger(VerifyOneNoteSyncStatusTool.name);

  public constructor(
    private readonly deltaService: OneNoteDeltaService,
    private readonly syncService: OneNoteSyncService,
  ) {}

  @Tool({
    name: 'verify_onenote_sync_status',
    title: 'Verify OneNote Sync Status',
    description:
      'Check the current status of the OneNote sync integration for the authenticated user.',
    parameters: z.object({}),
    outputSchema: VerifySyncStatusOutputSchema,
    annotations: {
      title: 'Verify OneNote Sync Status',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'info',
      'unique.app/system-prompt':
        'Use this tool only when the user explicitly asks about their sync status or connection health. ' +
        'Do not call this tool automatically before or after other tools.',
      'unique.app/tool-format-information':
        'Always relay the statusNote to the user — it provides a complete human-readable summary of the sync state, including any throttling or delays.',
    },
  })
  @Span()
  public async verifySyncStatus(
    _input: Record<string, never>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof VerifySyncStatusOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log({ userProfileId }, 'Tool verify_onenote_sync_status called');

    const state = await this.deltaService.getDeltaStatus(userProfileId);
    const isSyncRunning = this.syncService.isSyncRunning(userProfileId);
    const throttleRemainingMs = GlobalThrottleMiddleware.currentThrottleRemainingMs(userProfileId);

    const statusParts: string[] = [];

    if (!state) {
      statusParts.push('No sync has been completed yet for your OneNote notebooks.');
      if (isSyncRunning) {
        statusParts.push('A sync is currently running — your notebooks are being imported.');
      } else {
        statusParts.push('Syncs run automatically in the background when you connect.');
      }
      if (throttleRemainingMs > 0) {
        statusParts.push(`Microsoft OneNote is temporarily rate-limiting requests (~${Math.round(throttleRemainingMs / 1000)}s remaining). Syncing may take a bit longer.`);
      }
      return {
        status: 'inactive',
        message: 'No sync has been performed yet.',
        isSyncRunning,
        statusNote: statusParts.join(' '),
      };
    }

    const isDisabled = state.lastSyncStatus === 'disabled';
    const isError = state.lastSyncStatus === 'error';

    const status = isDisabled
      ? ('disabled' as const)
      : isError
        ? ('error' as const)
        : ('active' as const);

    if (status === 'disabled') {
      statusParts.push('OneNote sync is currently disabled.');
    } else if (status === 'error') {
      statusParts.push('The last sync encountered an error.');
    } else {
      statusParts.push('OneNote sync is active and working.');
    }

    if (state.lastSyncedAt) {
      const ago = Math.round((Date.now() - state.lastSyncedAt.getTime()) / 1000);
      if (ago < 120) {
        statusParts.push('Data was synced recently and should be up to date.');
      } else {
        statusParts.push(`Last sync was ${Math.round(ago / 60)} minutes ago.`);
      }
    }

    if (isSyncRunning) {
      statusParts.push('A sync is currently running in the background.');
    }

    if (throttleRemainingMs > 0) {
      statusParts.push(`Microsoft OneNote is temporarily rate-limiting requests (~${Math.round(throttleRemainingMs / 1000)}s remaining). This resolves on its own.`);
    }

    return {
      status,
      message: status === 'disabled'
        ? 'OneNote sync is disabled.'
        : status === 'error'
          ? 'Last sync encountered an error.'
          : 'OneNote sync is active.',
      lastSyncedAt: state.lastSyncedAt?.toISOString(),
      lastSyncStatus: state.lastSyncStatus ?? undefined,
      isSyncRunning,
      statusNote: statusParts.join(' '),
    };
  }
}
