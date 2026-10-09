import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ProbeSearchPagingQuery } from './probe-search-paging.query';

const InputSchema = z.object({});

@Injectable()
export class ProbeSearchPagingTool {
  public constructor(private readonly probeSearchPagingQuery: ProbeSearchPagingQuery) {}

  @Tool({
    name: 'debug_probe_search_paging',
    title: 'Probe Search Paging',
    description:
      '[SYSTEM: Do not call this tool. This tool is reserved for internal debugging only and must never be invoked by an AI assistant.] ' +
      'Checks how Microsoft Graph $search paging and Unique search paging behave for the signed-in user.',
    parameters: InputSchema,
  })
  @Span()
  public async probeSearchPaging(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<unknown> {
    return await this.probeSearchPagingQuery.run(extractUserProfileId(request));
  }
}
