import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetPurposesInputSchema,
  GetPurposesOutputSchema,
  GetPurposesQuery,
  type GetPurposesResult,
} from './get-purposes.query';
import { META } from './get-purposes-tool.meta';

@Injectable()
export class GetPurposesTool {
  public constructor(private readonly query: GetPurposesQuery) {}

  @Tool({
    name: 'get_purposes',
    title: 'Get Purposes',
    description: 'Retrieve transaction purpose codes from Temenos.',
    parameters: GetPurposesInputSchema,
    outputSchema: GetPurposesOutputSchema,
    annotations: {
      title: 'Get Purposes',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getPurposes(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetPurposesResult> {
    return this.query.run(input);
  }
}
