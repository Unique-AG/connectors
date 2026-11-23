import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { TemenosHeaderSchema, TitledRecordsSchema, toTitledRecords } from '../../../titled-records';

export const GetAccountOfficersInputSchema = z.object({});

export type GetAccountOfficersInput = z.infer<typeof GetAccountOfficersInputSchema>;

export const GetAccountOfficersOutputSchema = z
  .object({
    success: z.boolean(),
    data: TitledRecordsSchema.optional(),
    header: TemenosHeaderSchema.optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetAccountOfficersResult = z.infer<typeof GetAccountOfficersOutputSchema>;

@Injectable()
export class GetAccountOfficersQuery {
  private readonly logger = new Logger(GetAccountOfficersQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetAccountOfficersResult> {
    this.logger.debug({}, 'get_account_officers: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const response = await this.client.get<unknown>('/reference/accountOfficers', undefined);
      return { success: true, ...toTitledRecords(response, 'Account officer') };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_account_officers', result, start);
    }
  }
}
