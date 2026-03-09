import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { OneNoteDeltaService } from '../onenote-delta.service';

const VerifySyncStatusOutputSchema = z.object({
  status: z.enum(['active', 'inactive', 'error']),
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

    const isError = state.lastSyncStatus === 'error';

    return {
      status: isError ? 'error' : 'active',
      message: isError ? 'Last sync encountered an error' : 'OneNote sync is active',
      lastSyncedAt: state.lastSyncedAt?.toISOString(),
      lastSyncStatus: state.lastSyncStatus ?? undefined,
    };
  }
}
