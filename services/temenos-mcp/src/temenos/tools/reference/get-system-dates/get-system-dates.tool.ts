import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetSystemDatesInputSchema, GetSystemDatesOutputSchema, GetSystemDatesQuery, type GetSystemDatesResult } from './get-system-dates.query';
import { META } from './get-system-dates-tool.meta';

@Injectable()
export class GetSystemDatesTool {
  public constructor(private readonly query: GetSystemDatesQuery) {}

  @Tool({
    name: 'get_system_dates',
    title: 'Get System Business Dates',
    description: 'Retrieve system business date information from Temenos, including current, next, and last working dates.',
    parameters: GetSystemDatesInputSchema,
    outputSchema: GetSystemDatesOutputSchema,
    annotations: {
      title: 'Get System Business Dates',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getSystemDates(
    input: z.infer<typeof GetSystemDatesInputSchema>,
    _context: Context,
  ): Promise<GetSystemDatesResult> {
    return this.query.run(input as never);
  }
}
