import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetBalanceTypesInputSchema,
  GetBalanceTypesOutputSchema,
  GetBalanceTypesQuery,
  type GetBalanceTypesResult,
} from './get-balance-types.query';
import { META } from './get-balance-types-tool.meta';

@Injectable()
export class GetBalanceTypesTool {
  public constructor(private readonly query: GetBalanceTypesQuery) {}

  @Tool({
    name: 'get_balance_types',
    title: 'Get Balance Types',
    description: 'Retrieve balance type definitions from Temenos.',
    parameters: GetBalanceTypesInputSchema,
    outputSchema: GetBalanceTypesOutputSchema,
    annotations: {
      title: 'Get Balance Types',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getBalanceTypes(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetBalanceTypesResult> {
    return this.query.run(input as never);
  }
}
