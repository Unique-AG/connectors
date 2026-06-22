import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetUsCustomerRatingsInputSchema,
  GetUsCustomerRatingsOutputSchema,
  GetUsCustomerRatingsQuery,
  type GetUsCustomerRatingsResult,
} from './get-us-customer-ratings.query';
import { META } from './get-us-customer-ratings-tool.meta';

@Injectable()
export class GetUsCustomerRatingsTool {
  public constructor(private readonly query: GetUsCustomerRatingsQuery) {}

  @Tool({
    name: 'get_us_customer_ratings',
    title: 'Get US Customer Risk Ratings',
    description: 'Retrieve US model bank customer risk rating codes from Temenos.',
    parameters: GetUsCustomerRatingsInputSchema,
    outputSchema: GetUsCustomerRatingsOutputSchema,
    annotations: {
      title: 'Get US Customer Risk Ratings',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsCustomerRatings(
    input: z.infer<typeof GetUsCustomerRatingsInputSchema>,
    _context: Context,
  ): Promise<GetUsCustomerRatingsResult> {
    return this.query.run(input as never);
  }
}
