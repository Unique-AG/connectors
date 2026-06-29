import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetUtilityBeneficiariesInputSchema,
  GetUtilityBeneficiariesOutputSchema,
  GetUtilityBeneficiariesQuery,
  type GetUtilityBeneficiariesResult,
} from './get-utility-beneficiaries.query';
import { META } from './get-utility-beneficiaries-tool.meta';

@Injectable()
export class GetUtilityBeneficiariesTool {
  public constructor(private readonly query: GetUtilityBeneficiariesQuery) {}

  @Tool({
    name: 'get_utility_beneficiaries',
    title: 'Get Utility Beneficiaries',
    description:
      'Retrieve utility beneficiary details from Temenos. Supports extensive filtering by product, account, IBAN, or customer.',
    parameters: GetUtilityBeneficiariesInputSchema,
    outputSchema: GetUtilityBeneficiariesOutputSchema,
    annotations: {
      title: 'Get Utility Beneficiaries',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUtilityBeneficiaries(
    input: z.infer<typeof GetUtilityBeneficiariesInputSchema>,
    _context: Context,
  ): Promise<GetUtilityBeneficiariesResult> {
    return this.query.run(input);
  }
}
