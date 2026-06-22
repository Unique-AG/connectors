import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetUsCustomerRatingsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
});

export type GetUsCustomerRatingsInput = z.infer<typeof GetUsCustomerRatingsInputSchema>;

export const GetUsCustomerRatingsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetUsCustomerRatingsResult = z.infer<typeof GetUsCustomerRatingsOutputSchema>;

@Injectable()
export class GetUsCustomerRatingsQuery {
  private readonly logger = new Logger(GetUsCustomerRatingsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetUsCustomerRatingsInput): Promise<GetUsCustomerRatingsResult> {
    this.logger.debug({}, 'get_us_customer_ratings: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/reference/us/customerRatings', {
        recordId: input.recordId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_us_customer_ratings', result, start);
    }
  }
}
