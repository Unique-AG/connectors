import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetRateTextsInputSchema,
  GetRateTextsOutputSchema,
  GetRateTextsQuery,
  type GetRateTextsResult,
} from './get-rate-texts.query';
import { META } from './get-rate-texts-tool.meta';

@Injectable()
export class GetRateTextsTool {
  public constructor(private readonly query: GetRateTextsQuery) {}

  @Tool({
    name: 'get_rate_texts',
    title: 'Get Interest Rate Descriptions',
    description: 'Retrieve interest rate description texts from Temenos.',
    parameters: GetRateTextsInputSchema,
    outputSchema: GetRateTextsOutputSchema,
    annotations: {
      title: 'Get Interest Rate Descriptions',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getRateTexts(
    input: z.infer<typeof GetRateTextsInputSchema>,
    _context: Context,
  ): Promise<GetRateTextsResult> {
    return this.query.run(input);
  }
}
