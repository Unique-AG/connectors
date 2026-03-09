import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { OneNoteDeltaService } from '../onenote-delta.service';

const VerifySyncStatusOutputSchema = z.object({
  status: z.enum(['active', 'inactive', 'disabled', 'error']),
  message: z.string(),
  lastSyncedAt: z.string().optional(),
  lastSyncStatus: z.string().optional(),
});

@Injectable()
export class VerifyOneNoteSyncStatusTool {
  public constructor(private readonly deltaService: OneNoteDeltaService) {}

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

    const state = await this.deltaService.getDeltaStatus(userProfileId);

    if (!state) {
      return {
        status: 'inactive',
        message: 'No sync has been performed yet. Use start_onenote_sync to begin.',
      };
    }

    const isDisabled = state.lastSyncStatus === 'disabled';
    const isError = state.lastSyncStatus === 'error';

    const status = isDisabled
      ? ('disabled' as const)
      : isError
        ? ('error' as const)
        : ('active' as const);
    const messageMap = {
      disabled: 'OneNote sync is disabled. Use start_onenote_sync to re-enable.',
      error: 'Last sync encountered an error',
      active: 'OneNote sync is active',
    } as const;

    return {
      status,
      message: messageMap[status],
      lastSyncedAt: state.lastSyncedAt?.toISOString(),
      lastSyncStatus: state.lastSyncStatus ?? undefined,
    };
  }
}
