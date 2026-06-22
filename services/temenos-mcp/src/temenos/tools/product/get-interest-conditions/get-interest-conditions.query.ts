import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetInterestConditionsInputSchema = z.object({});

export type GetInterestConditionsInput = z.infer<typeof GetInterestConditionsInputSchema>;

export const GetInterestConditionsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetInterestConditionsResult = z.infer<typeof GetInterestConditionsOutputSchema>;

@Injectable()
export class GetInterestConditionsQuery {
  private readonly logger = new Logger(GetInterestConditionsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetInterestConditionsResult> {
    this.logger.debug({}, 'get_interest_conditions: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/product/interestConditions', undefined);
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_interest_conditions', result, start);
    }
  }
}
