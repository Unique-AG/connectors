import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetLetterOfCreditTenorsInputSchema,
  GetLetterOfCreditTenorsOutputSchema,
  GetLetterOfCreditTenorsQuery,
  type GetLetterOfCreditTenorsResult,
} from './get-letter-of-credit-tenors.query';
import { META } from './get-letter-of-credit-tenors-tool.meta';

@Injectable()
export class GetLetterOfCreditTenorsTool {
  public constructor(private readonly query: GetLetterOfCreditTenorsQuery) {}

  @Tool({
    name: 'get_letter_of_credit_tenors',
    title: 'Get Letter of Credit Tenors',
    description: 'Retrieve tenor details for letters of credit from Temenos.',
    parameters: GetLetterOfCreditTenorsInputSchema,
    outputSchema: GetLetterOfCreditTenorsOutputSchema,
    annotations: {
      title: 'Get Letter of Credit Tenors',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getLetterOfCreditTenors(
    input: z.infer<typeof GetLetterOfCreditTenorsInputSchema>,
    _context: Context,
  ): Promise<GetLetterOfCreditTenorsResult> {
    return this.query.run(input as never);
  }
}
