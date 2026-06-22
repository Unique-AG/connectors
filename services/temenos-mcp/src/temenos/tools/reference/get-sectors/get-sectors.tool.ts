import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  GetSectorsInputSchema,
  GetSectorsOutputSchema,
  GetSectorsQuery,
  type GetSectorsResult,
} from './get-sectors.query';
import { META } from './get-sectors-tool.meta';

@Injectable()
export class GetSectorsTool {
  public constructor(private readonly query: GetSectorsQuery) {}

  @Tool({
    name: 'get_sectors',
    title: 'Get Sectors',
    description: 'Retrieve sector classification codes from Temenos.',
    parameters: GetSectorsInputSchema,
    outputSchema: GetSectorsOutputSchema,
    annotations: {
      title: 'Get Sectors',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getSectors(
    input: Record<string, never>,
    _context: Context,
  ): Promise<GetSectorsResult> {
    return this.query.run(input as never);
  }
}
