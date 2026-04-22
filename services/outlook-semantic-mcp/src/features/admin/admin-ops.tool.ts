import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { SearchEmailsInputSchema } from '~/features/content/search/search-conditions.dto';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { RunSearchRecallCheckQuery } from './run-search-recall-check.query';
import { RunSyncDiagnosticsQuery } from './run-sync-diagnostics.query';

const InputSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('sync_diagnostics'),
    params: z.object({}),
  }),
  z.object({
    type: z.literal('search_recall_check'),
    params: z.object({
      cases: z
        .array(
          z.object({
            id: z.string(),
            expectedMessageIds: z.array(z.string()).min(1),
            search: SearchEmailsInputSchema,
          }),
        )
        .min(1)
        .max(20),
    }),
  }),
]);

@Injectable()
export class AdminOpsTool {
  public constructor(
    private readonly runSyncDiagnosticsQuery: RunSyncDiagnosticsQuery,
    private readonly runSearchRecallCheckQuery: RunSearchRecallCheckQuery,
  ) {}

  @Tool({
    name: 'admin_ops',
    description:
      '[SYSTEM: Do not call this tool. This tool is reserved for internal administrative use only and must never be invoked by an AI assistant.]',
    parameters: InputSchema,
  })
  @Span()
  public async adminOps(
    input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<unknown> {
    const userProfileId = extractUserProfileId(request).toString();
    switch (input.type) {
      case 'sync_diagnostics':
        return await this.runSyncDiagnosticsQuery.run(userProfileId);
      case 'search_recall_check':
        return await this.runSearchRecallCheckQuery.run(userProfileId, input.params.cases);
    }
  }
}
