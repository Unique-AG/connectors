import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetLimitMasterGroupsInputSchema,
  GetLimitMasterGroupsOutputSchema,
  GetLimitMasterGroupsQuery,
  type GetLimitMasterGroupsResult,
} from './get-limit-master-groups.query';
import { META } from './get-limit-master-groups-tool.meta';

@Injectable()
export class GetLimitMasterGroupsTool {
  public constructor(private readonly query: GetLimitMasterGroupsQuery) {}

  @Tool({
    name: 'get_limit_master_groups',
    title: 'Get Limit Master Groups',
    description: 'Retrieve customer limit master group details from Temenos.',
    parameters: GetLimitMasterGroupsInputSchema,
    outputSchema: GetLimitMasterGroupsOutputSchema,
    annotations: {
      title: 'Get Limit Master Groups',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getLimitMasterGroups(
    input: z.infer<typeof GetLimitMasterGroupsInputSchema>,
    _context: Context,
  ): Promise<GetLimitMasterGroupsResult> {
    return this.query.run(input);
  }
}
