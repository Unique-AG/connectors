import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetLetterOfCreditIncoTermsInputSchema, GetLetterOfCreditIncoTermsOutputSchema, GetLetterOfCreditIncoTermsQuery, type GetLetterOfCreditIncoTermsResult } from './get-letter-of-credit-inco-terms.query';
import { META } from './get-letter-of-credit-inco-terms-tool.meta';

@Injectable()
export class GetLetterOfCreditIncoTermsTool {
  public constructor(private readonly query: GetLetterOfCreditIncoTermsQuery) {}

  @Tool({
    name: 'get_letter_of_credit_inco_terms',
    title: 'Get Letter of Credit Inco Terms',
    description: 'Retrieve Incoterms associated with letters of credit from Temenos.',
    parameters: GetLetterOfCreditIncoTermsInputSchema,
    outputSchema: GetLetterOfCreditIncoTermsOutputSchema,
    annotations: {
      title: 'Get Letter of Credit Inco Terms',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getLetterOfCreditIncoTerms(
    input: z.infer<typeof GetLetterOfCreditIncoTermsInputSchema>,
    _context: Context,
  ): Promise<GetLetterOfCreditIncoTermsResult> {
    return this.query.run(input as never);
  }
}
