import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetUsBeneficialOwnerTypesInputSchema,
  GetUsBeneficialOwnerTypesOutputSchema,
  GetUsBeneficialOwnerTypesQuery,
  type GetUsBeneficialOwnerTypesResult,
} from './get-us-beneficial-owner-types.query';
import { META } from './get-us-beneficial-owner-types-tool.meta';

@Injectable()
export class GetUsBeneficialOwnerTypesTool {
  public constructor(private readonly query: GetUsBeneficialOwnerTypesQuery) {}

  @Tool({
    name: 'get_us_beneficial_owner_types',
    title: 'Get US Beneficial Owner Types',
    description: 'Retrieve US model bank beneficial owner type codes from Temenos.',
    parameters: GetUsBeneficialOwnerTypesInputSchema,
    outputSchema: GetUsBeneficialOwnerTypesOutputSchema,
    annotations: {
      title: 'Get US Beneficial Owner Types',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getUsBeneficialOwnerTypes(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetUsBeneficialOwnerTypesResult> {
    return this.query.run(input);
  }
}
