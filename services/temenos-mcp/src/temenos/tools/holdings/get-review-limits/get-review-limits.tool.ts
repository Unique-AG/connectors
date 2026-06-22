import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetReviewLimitsInputSchema,
  GetReviewLimitsOutputSchema,
  GetReviewLimitsQuery,
  type GetReviewLimitsResult,
} from './get-review-limits.query';
import { META } from './get-review-limits-tool.meta';

@Injectable()
export class GetReviewLimitsTool {
  public constructor(private readonly query: GetReviewLimitsQuery) {}

  @Tool({
    name: 'get_review_limits',
    title: 'Get Review Limits',
    description:
      'Retrieve credit limits due for review from Temenos. Filter by review date, approval date, or liability number.',
    parameters: GetReviewLimitsInputSchema,
    outputSchema: GetReviewLimitsOutputSchema,
    annotations: {
      title: 'Get Review Limits',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getReviewLimits(
    input: z.infer<typeof GetReviewLimitsInputSchema>,
    _context: Context,
  ): Promise<GetReviewLimitsResult> {
    return this.query.run(input as never);
  }
}
