import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetDealersInputSchema,
  GetDealersOutputSchema,
  GetDealersQuery,
  type GetDealersResult,
} from './get-dealers.query';
import { META } from './get-dealers-tool.meta';

@Injectable()
export class GetDealersTool {
  public constructor(private readonly query: GetDealersQuery) {}

  @Tool({
    name: 'get_dealers',
    title: 'Get Treasury Dealer Desks',
    description: 'Retrieve treasury dealer desk definitions from Temenos.',
    parameters: GetDealersInputSchema,
    outputSchema: GetDealersOutputSchema,
    annotations: {
      title: 'Get Treasury Dealer Desks',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getDealers(
    input: z.infer<typeof GetDealersInputSchema>,
    _context: Context,
  ): Promise<GetDealersResult> {
    return this.query.run(input);
  }
}
