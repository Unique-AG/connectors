import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetUsIndustriesInputSchema,
  GetUsIndustriesOutputSchema,
  GetUsIndustriesQuery,
  type GetUsIndustriesResult,
} from './get-us-industries.query';
import { META } from './get-us-industries-tool.meta';

@Injectable()
export class GetUsIndustriesTool {
  public constructor(private readonly query: GetUsIndustriesQuery) {}

  @Tool({
    name: 'get_us_industries',
    title: 'Get US Industry Classifications',
    description: 'Retrieve US industry classification codes from the Temenos US model bank.',
    parameters: GetUsIndustriesInputSchema,
    outputSchema: GetUsIndustriesOutputSchema,
    annotations: {
      title: 'Get US Industry Classifications',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsIndustries(
    input: z.infer<typeof GetUsIndustriesInputSchema>,
    _context: Context,
  ): Promise<GetUsIndustriesResult> {
    return this.query.run(input as never);
  }
}
