import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetBrokersInputSchema,
  GetBrokersOutputSchema,
  GetBrokersQuery,
  type GetBrokersResult,
} from './get-brokers.query';
import { META } from './get-brokers-tool.meta';

@Injectable()
export class GetBrokersTool {
  public constructor(private readonly query: GetBrokersQuery) {}

  @Tool({
    name: 'get_brokers',
    title: 'Get Brokers',
    description: 'Retrieve the list of brokers from Temenos.',
    parameters: GetBrokersInputSchema,
    outputSchema: GetBrokersOutputSchema,
    annotations: {
      title: 'Get Brokers',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getBrokers(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetBrokersResult> {
    return this.query.run(input);
  }
}
