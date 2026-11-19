import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosRecordsOutputSchema, toTitledRecords } from '../../../titled-records';

export const GetCustomerProspectsInputSchema = z.object({});

export type GetCustomerProspectsInput = z.infer<typeof GetCustomerProspectsInputSchema>;

export const GetCustomerProspectsOutputSchema = TemenosRecordsOutputSchema;

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
      const response = await this.client.get<unknown>('/party/customers/prospects', undefined);
      return { success: true, ...toTitledRecords(response, 'Prospect') };
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
