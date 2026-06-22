import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetCustomerProspectsInputSchema, GetCustomerProspectsOutputSchema, GetCustomerProspectsQuery, type GetCustomerProspectsResult } from './get-customer-prospects.query';
import { META } from './get-customer-prospects-tool.meta';

@Injectable()
export class GetCustomerProspectsTool {
  public constructor(private readonly query: GetCustomerProspectsQuery) {}

  @Tool({
    name: 'get_customer_prospects',
    title: 'Get Customer Prospects',
    description: 'Retrieve prospective customer records from Temenos.',
    parameters: GetCustomerProspectsInputSchema,
    outputSchema: GetCustomerProspectsOutputSchema,
    annotations: {
      title: 'Get Customer Prospects',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCustomerProspects(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetCustomerProspectsResult> {
    return this.query.run(input as never);
  }
}
