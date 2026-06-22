import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetCustomerRelationshipsInputSchema,
  GetCustomerRelationshipsOutputSchema,
  GetCustomerRelationshipsQuery,
  type GetCustomerRelationshipsResult,
} from './get-customer-relationships.query';
import { META } from './get-customer-relationships-tool.meta';

@Injectable()
export class GetCustomerRelationshipsTool {
  public constructor(private readonly query: GetCustomerRelationshipsQuery) {}

  @Tool({
    name: 'get_customer_relationships',
    title: 'Get Customer Relationships',
    description:
      'Retrieve customer relationship group data from Temenos. Filter by group ID, party, or related party.',
    parameters: GetCustomerRelationshipsInputSchema,
    outputSchema: GetCustomerRelationshipsOutputSchema,
    annotations: {
      title: 'Get Customer Relationships',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCustomerRelationships(
    input: z.infer<typeof GetCustomerRelationshipsInputSchema>,
    _context: Context,
  ): Promise<GetCustomerRelationshipsResult> {
    return this.query.run(input as never);
  }
}
