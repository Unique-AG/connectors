import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetFullSyncStatsQuery, GetFullSyncStatsResponse } from '../get-full-sync-stats.query';
import { META } from './sync-progress.meta';

const InputSchema = z.object({});

const OutputSchema = GetFullSyncStatsResponse;

@Injectable()
export class SyncProgressTool {
  public constructor(private readonly getFullSyncStatsQuery: GetFullSyncStatsQuery) {}

  @Tool({
    name: 'os_mcp_sync_progress',
    title: 'Sync Progress',
    description:
      'Check the current progress of the full email sync. Returns inbox configuration details and ingestion statistics. Use after `os_mcp_run_full_sync` to monitor progress, or when `os_mcp_search_emails` returns a `syncWarning`.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Sync Progress',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async fullSyncProgress(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    return await this.getFullSyncStatsQuery.run(userProfileTypeid);
  }
}
