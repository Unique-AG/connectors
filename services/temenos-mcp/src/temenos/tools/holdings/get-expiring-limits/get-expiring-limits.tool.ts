import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetExpiringLimitsInputSchema,
  GetExpiringLimitsOutputSchema,
  GetExpiringLimitsQuery,
  type GetExpiringLimitsResult,
} from './get-expiring-limits.query';
import { META } from './get-expiring-limits-tool.meta';

@Injectable()
export class GetExpiringLimitsTool {
  public constructor(private readonly query: GetExpiringLimitsQuery) {}

  @Tool({
    name: 'get_expiring_limits',
    title: 'Get Expiring Limits',
    description:
      'Retrieve credit limits approaching expiry from Temenos. Filter by expiry date or approval date.',
    parameters: GetExpiringLimitsInputSchema,
    outputSchema: GetExpiringLimitsOutputSchema,
    annotations: {
      title: 'Get Expiring Limits',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getExpiringLimits(
    input: z.infer<typeof GetExpiringLimitsInputSchema>,
    _context: Context,
  ): Promise<GetExpiringLimitsResult> {
    return this.query.run(input);
  }
}
