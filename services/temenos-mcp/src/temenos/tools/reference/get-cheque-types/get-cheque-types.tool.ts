import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetChequeTypesInputSchema, GetChequeTypesOutputSchema, GetChequeTypesQuery, type GetChequeTypesResult } from './get-cheque-types.query';
import { META } from './get-cheque-types-tool.meta';

@Injectable()
export class GetChequeTypesTool {
  public constructor(private readonly query: GetChequeTypesQuery) {}

  @Tool({
    name: 'get_cheque_types',
    title: 'Get Cheque Types',
    description: 'Retrieve cheque type definitions from Temenos. Optionally filter by product name.',
    parameters: GetChequeTypesInputSchema,
    outputSchema: GetChequeTypesOutputSchema,
    annotations: {
      title: 'Get Cheque Types',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getChequeTypes(
    input: z.infer<typeof GetChequeTypesInputSchema>,
    _context: Context,
  ): Promise<GetChequeTypesResult> {
    return this.query.run(input as never);
  }
}
