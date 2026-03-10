import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { GetFullSyncStatsQuery, GetFullSyncStatsResponse } from './get-full-sync-stats.query';

const InputSchema = z.object({});

// When inbox is not connected, only `message` is populated and configuration fields are null.
const OutputSchema = GetFullSyncStatsResponse.extend({
  message: z.string(),
});

@Injectable()
export class SyncProgressTool {
  public constructor(private readonly getFullSyncStatsQuery: GetFullSyncStatsQuery) {}

  @Tool({
    name: 'sync_progress',
    title: 'Sync Progress',
    description:
      'Check the current progress of the full email sync. Returns inbox configuration details and ingestion statistics from the knowledge base.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Sync Progress',
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
    const stats = await this.getFullSyncStatsQuery.run(userProfileTypeid);
    if (stats.state === 'unknown') {
      return {
        ...stats,
        message:
          'Search results may be inaccurate. Ingestion Statistics could not be fetched. Your inbox is a unknown state try to use the tools `remove_inbox_connection` and `reconnect_inbox` to get it into a proper state',
      };
    }
    if (stats.state === 'running') {
      return {
        ...stats,
        message:
          'Email ingestion is still in progress. Search results may be incomplete and not reflect all emails in the inbox.',
      };
    }

    return { ...stats, message: '' };
  }
}
