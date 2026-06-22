import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetCustomerProspectsInputSchema = z.object({});

export type GetCustomerProspectsInput = z.infer<typeof GetCustomerProspectsInputSchema>;

export const GetCustomerProspectsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetCustomerProspectsResult = z.infer<typeof GetCustomerProspectsOutputSchema>;

@Injectable()
export class GetCustomerProspectsQuery {
  private readonly logger = new Logger(GetCustomerProspectsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetCustomerProspectsResult> {
    this.logger.debug({}, 'get_customer_prospects: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/party/customers/prospects', undefined);
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_customer_prospects', result, start);
    }
  }
}
