import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetLookupsInputSchema = z.object({
  virtualTable: z.string().optional().describe("Table name derived from the EB.LOOKUP table ID"),
  otherInfo: z.string().optional().describe("Additional lookup information"),
});

export type GetLookupsInput = z.infer<typeof GetLookupsInputSchema>;

export const GetLookupsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetLookupsResult = z.infer<typeof GetLookupsOutputSchema>;

@Injectable()
export class GetLookupsQuery {
  private readonly logger = new Logger(GetLookupsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetLookupsInput): Promise<GetLookupsResult> {
    this.logger.debug({}, 'get_lookups: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/lookups', {
        virtualTable: input.virtualTable,
        otherInfo: input.otherInfo,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_lookups', result, start);
    }
  }
}
