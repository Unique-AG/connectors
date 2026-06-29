import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetUsHoldTypesInputSchema,
  GetUsHoldTypesOutputSchema,
  GetUsHoldTypesQuery,
  type GetUsHoldTypesResult,
} from './get-us-hold-types.query';
import { META } from './get-us-hold-types-tool.meta';

@Injectable()
export class GetUsHoldTypesTool {
  public constructor(private readonly query: GetUsHoldTypesQuery) {}

  @Tool({
    name: 'get_us_hold_types',
    title: 'Get US Hold Types',
    description: 'Retrieve US model bank hold type codes from Temenos.',
    parameters: GetUsHoldTypesInputSchema,
    outputSchema: GetUsHoldTypesOutputSchema,
    annotations: {
      title: 'Get US Hold Types',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsHoldTypes(
    input: z.infer<typeof GetUsHoldTypesInputSchema>,
    _context: Context,
  ): Promise<GetUsHoldTypesResult> {
    return this.query.run(input);
  }
}
