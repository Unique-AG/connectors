import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetGuaranteesInputSchema, GetGuaranteesOutputSchema, GetGuaranteesQuery, type GetGuaranteesResult } from './get-guarantees.query';
import { META } from './get-guarantees-tool.meta';

@Injectable()
export class GetGuaranteesTool {
  public constructor(private readonly query: GetGuaranteesQuery) {}

  @Tool({
    name: 'get_guarantees',
    title: 'Get Guarantees',
    description: 'Retrieve guarantee request details from Temenos. Optionally filter by record ID, customer ID, or event status.',
    parameters: GetGuaranteesInputSchema,
    outputSchema: GetGuaranteesOutputSchema,
    annotations: {
      title: 'Get Guarantees',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getGuarantees(
    input: z.infer<typeof GetGuaranteesInputSchema>,
    _context: Context,
  ): Promise<GetGuaranteesResult> {
    return this.query.run(input as never);
  }
}
