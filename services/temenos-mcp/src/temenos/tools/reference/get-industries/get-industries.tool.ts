import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetIndustriesInputSchema,
  GetIndustriesOutputSchema,
  GetIndustriesQuery,
  type GetIndustriesResult,
} from './get-industries.query';
import { META } from './get-industries-tool.meta';

@Injectable()
export class GetIndustriesTool {
  public constructor(private readonly query: GetIndustriesQuery) {}

  @Tool({
    name: 'get_industries',
    title: 'Get Industries',
    description: 'Retrieve industry classification codes from Temenos.',
    parameters: GetIndustriesInputSchema,
    outputSchema: GetIndustriesOutputSchema,
    annotations: {
      title: 'Get Industries',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getIndustries(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetIndustriesResult> {
    return this.query.run(input);
  }
}
