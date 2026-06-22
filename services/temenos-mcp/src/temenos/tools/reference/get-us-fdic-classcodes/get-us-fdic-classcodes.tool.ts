import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetUsFdicClasscodesInputSchema, GetUsFdicClasscodesOutputSchema, GetUsFdicClasscodesQuery, type GetUsFdicClasscodesResult } from './get-us-fdic-classcodes.query';
import { META } from './get-us-fdic-classcodes-tool.meta';

@Injectable()
export class GetUsFdicClasscodesTool {
  public constructor(private readonly query: GetUsFdicClasscodesQuery) {}

  @Tool({
    name: 'get_us_fdic_classcodes',
    title: 'Get US FDIC Subclassification Codes',
    description: 'Retrieve FDIC subclassification codes from the Temenos US model bank.',
    parameters: GetUsFdicClasscodesInputSchema,
    outputSchema: GetUsFdicClasscodesOutputSchema,
    annotations: {
      title: 'Get US FDIC Subclassification Codes',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsFdicClasscodes(
    input: z.infer<typeof GetUsFdicClasscodesInputSchema>,
    _context: Context,
  ): Promise<GetUsFdicClasscodesResult> {
    return this.query.run(input as never);
  }
}
