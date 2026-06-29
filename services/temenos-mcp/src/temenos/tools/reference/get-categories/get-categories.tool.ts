import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetCategoriesInputSchema,
  GetCategoriesOutputSchema,
  GetCategoriesQuery,
  type GetCategoriesResult,
} from './get-categories.query';
import { META } from './get-categories-tool.meta';

@Injectable()
export class GetCategoriesTool {
  public constructor(private readonly query: GetCategoriesQuery) {}

  @Tool({
    name: 'get_categories',
    title: 'Get Product Categories',
    description: 'Retrieve internal product category codes from Temenos.',
    parameters: GetCategoriesInputSchema,
    outputSchema: GetCategoriesOutputSchema,
    annotations: {
      title: 'Get Product Categories',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCategories(
    input: z.infer<typeof GetCategoriesInputSchema>,
    _context: Context,
  ): Promise<GetCategoriesResult> {
    return this.query.run(input);
  }
}
