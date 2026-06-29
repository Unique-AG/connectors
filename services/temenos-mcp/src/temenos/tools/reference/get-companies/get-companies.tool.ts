import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetCompaniesInputSchema,
  GetCompaniesOutputSchema,
  GetCompaniesQuery,
  type GetCompaniesResult,
} from './get-companies.query';
import { META } from './get-companies-tool.meta';

@Injectable()
export class GetCompaniesTool {
  public constructor(private readonly query: GetCompaniesQuery) {}

  @Tool({
    name: 'get_companies',
    title: 'Get Legal Entities',
    description: 'Retrieve the list of legal entities (companies) defined in the Temenos system.',
    parameters: GetCompaniesInputSchema,
    outputSchema: GetCompaniesOutputSchema,
    annotations: {
      title: 'Get Legal Entities',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCompanies(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetCompaniesResult> {
    return this.query.run(input);
  }
}
