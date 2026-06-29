import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetSharedLimitsInputSchema,
  GetSharedLimitsOutputSchema,
  GetSharedLimitsQuery,
  type GetSharedLimitsResult,
} from './get-shared-limits.query';
import { META } from './get-shared-limits-tool.meta';

@Injectable()
export class GetSharedLimitsTool {
  public constructor(private readonly query: GetSharedLimitsQuery) {}

  @Tool({
    name: 'get_shared_limits',
    title: 'Get Shared Limits',
    description: 'Retrieve shared credit limit details from Temenos.',
    parameters: GetSharedLimitsInputSchema,
    outputSchema: GetSharedLimitsOutputSchema,
    annotations: {
      title: 'Get Shared Limits',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getSharedLimits(
    input: z.infer<typeof GetSharedLimitsInputSchema>,
    _context: Context,
  ): Promise<GetSharedLimitsResult> {
    return this.query.run(input);
  }
}
