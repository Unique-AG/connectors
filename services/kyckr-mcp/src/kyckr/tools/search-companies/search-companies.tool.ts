import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  SearchCompaniesInputSchema,
  SearchCompaniesOutputSchema,
  SearchCompaniesQuery,
} from './search-companies.query';
import { META } from './search-companies-tool.meta';

@Injectable()
export class SearchCompaniesTool {
  public constructor(private readonly searchCompaniesQuery: SearchCompaniesQuery) {}

  @Tool({
    name: 'search_companies',
    title: 'Search Companies',
    description:
      "Search the Kyckr company registry by name or registration number. Either `name` or `companyNumber` must be provided. Pass `isoCode` (ISO 3166 alpha-2, e.g. 'GB', 'AU') to search a specific jurisdiction directly. Without `isoCode`, Kyckr performs a global search over stored data — once you locate the right jurisdiction, repeat the search with that `isoCode` to confirm the entity is currently active. The returned `id` is the KyckrId required by every other Kyckr tool, and is also the starting point for `list_company_documents`. Free to call.",
    parameters: SearchCompaniesInputSchema,
    outputSchema: SearchCompaniesOutputSchema,
    annotations: {
      title: 'Search Companies',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async searchCompanies(
    input: z.infer<typeof SearchCompaniesInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof SearchCompaniesOutputSchema>> {
    return this.searchCompaniesQuery.run(input);
  }
}
