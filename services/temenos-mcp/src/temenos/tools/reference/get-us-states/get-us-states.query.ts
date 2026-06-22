import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetUsStatesInputSchema = z.object({
  countryId: z.string().optional().describe("ISO country code of the financial institution"),
});

export type GetUsStatesInput = z.infer<typeof GetUsStatesInputSchema>;

export const GetUsStatesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetUsStatesResult = z.infer<typeof GetUsStatesOutputSchema>;

@Injectable()
export class GetUsStatesQuery {
  private readonly logger = new Logger(GetUsStatesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetUsStatesInput): Promise<GetUsStatesResult> {
    this.logger.debug({}, 'get_us_states: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/us/states', {
        countryId: input.countryId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_us_states', result, start);
    }
  }
}
