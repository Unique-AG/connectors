import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetCountriesInputSchema, GetCountriesOutputSchema, GetCountriesQuery, type GetCountriesResult } from './get-countries.query';
import { META } from './get-countries-tool.meta';

@Injectable()
export class GetCountriesTool {
  public constructor(private readonly query: GetCountriesQuery) {}

  @Tool({
    name: 'get_countries',
    title: 'Get Countries',
    description: 'Retrieve country code reference data from Temenos.',
    parameters: GetCountriesInputSchema,
    outputSchema: GetCountriesOutputSchema,
    annotations: {
      title: 'Get Countries',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCountries(
    input: z.infer<typeof GetCountriesInputSchema>,
    _context: Context,
  ): Promise<GetCountriesResult> {
    return this.query.run(input as never);
  }
}
