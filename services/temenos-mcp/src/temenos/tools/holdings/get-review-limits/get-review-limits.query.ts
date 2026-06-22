import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetReviewLimitsInputSchema = z.object({
  limitReviewDate: z.string().optional().describe("The next date on which the limit is reviewed"),
  approvalDate: z.string().optional().describe("The date the limit was last approved by the credit committee"),
  liabilityNumber: z.string().optional().describe("Identifier of the liability customer to the credit limit"),
});

export type GetReviewLimitsInput = z.infer<typeof GetReviewLimitsInputSchema>;

export const GetReviewLimitsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetReviewLimitsResult = z.infer<typeof GetReviewLimitsOutputSchema>;

@Injectable()
export class GetReviewLimitsQuery {
  private readonly logger = new Logger(GetReviewLimitsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetReviewLimitsInput): Promise<GetReviewLimitsResult> {
    this.logger.debug({}, 'get_review_limits: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/limits/reviewLimits', {
        limitReviewDate: input.limitReviewDate,
        approvalDate: input.approvalDate,
        liabilityNumber: input.liabilityNumber,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_review_limits', result, start);
    }
  }
}
