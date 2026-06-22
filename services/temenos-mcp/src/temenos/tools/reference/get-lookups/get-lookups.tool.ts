import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetLookupsInputSchema,
  GetLookupsOutputSchema,
  GetLookupsQuery,
  type GetLookupsResult,
} from './get-lookups.query';
import { META } from './get-lookups-tool.meta';

@Injectable()
export class GetLookupsTool {
  public constructor(private readonly query: GetLookupsQuery) {}

  @Tool({
    name: 'get_lookups',
    title: 'Get Lookup Tables',
    description:
      'Retrieve lookup table values from Temenos. Filter by virtual table name or other info.',
    parameters: GetLookupsInputSchema,
    outputSchema: GetLookupsOutputSchema,
    annotations: {
      title: 'Get Lookup Tables',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getLookups(
    input: z.infer<typeof GetLookupsInputSchema>,
    _context: Context,
  ): Promise<GetLookupsResult> {
    return this.query.run(input as never);
  }
}
