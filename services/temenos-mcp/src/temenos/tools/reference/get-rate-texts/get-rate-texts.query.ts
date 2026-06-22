import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetRateTextsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
  displayName: z.string().optional().describe("Name used for display purposes"),
});

export type GetRateTextsInput = z.infer<typeof GetRateTextsInputSchema>;

export const GetRateTextsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetRateTextsResult = z.infer<typeof GetRateTextsOutputSchema>;

@Injectable()
export class GetRateTextsQuery {
  private readonly logger = new Logger(GetRateTextsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetRateTextsInput): Promise<GetRateTextsResult> {
    this.logger.debug({}, 'get_rate_texts: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/rateTexts', {
        recordId: input.recordId,
        displayName: input.displayName,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_rate_texts', result, start);
    }
  }
}
