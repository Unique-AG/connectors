import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetUsStatesInputSchema, GetUsStatesOutputSchema, GetUsStatesQuery, type GetUsStatesResult } from './get-us-states.query';
import { META } from './get-us-states-tool.meta';

@Injectable()
export class GetUsStatesTool {
  public constructor(private readonly query: GetUsStatesQuery) {}

  @Tool({
    name: 'get_us_states',
    title: 'Get US States',
    description: 'Retrieve US state codes from the Temenos US model bank reference data.',
    parameters: GetUsStatesInputSchema,
    outputSchema: GetUsStatesOutputSchema,
    annotations: {
      title: 'Get US States',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsStates(
    input: z.infer<typeof GetUsStatesInputSchema>,
    _context: Context,
  ): Promise<GetUsStatesResult> {
    return this.query.run(input as never);
  }
}
