import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetExpiringLimitsInputSchema = z.object({
  expiryDate: z
    .string()
    .optional()
    .describe('The date the credit facility or limit is due to expire'),
  approvalDate: z
    .string()
    .optional()
    .describe('The date the limit was last approved by the credit committee'),
});

export type GetExpiringLimitsInput = z.infer<typeof GetExpiringLimitsInputSchema>;

export const GetExpiringLimitsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetExpiringLimitsResult = z.infer<typeof GetExpiringLimitsOutputSchema>;

@Injectable()
export class GetExpiringLimitsQuery {
  private readonly logger = new Logger(GetExpiringLimitsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetExpiringLimitsInput): Promise<GetExpiringLimitsResult> {
    this.logger.debug({}, 'get_expiring_limits: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/limits/expiringLimits', {
        expiryDate: input.expiryDate,
        approvalDate: input.approvalDate,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_expiring_limits', result, start);
    }
  }
}
