import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetLanguageCodesInputSchema, GetLanguageCodesOutputSchema, GetLanguageCodesQuery, type GetLanguageCodesResult } from './get-language-codes.query';
import { META } from './get-language-codes-tool.meta';

@Injectable()
export class GetLanguageCodesTool {
  public constructor(private readonly query: GetLanguageCodesQuery) {}

  @Tool({
    name: 'get_language_codes',
    title: 'Get Language Codes',
    description: 'Retrieve language code reference data from Temenos.',
    parameters: GetLanguageCodesInputSchema,
    outputSchema: GetLanguageCodesOutputSchema,
    annotations: {
      title: 'Get Language Codes',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getLanguageCodes(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetLanguageCodesResult> {
    return this.query.run(input as never);
  }
}
