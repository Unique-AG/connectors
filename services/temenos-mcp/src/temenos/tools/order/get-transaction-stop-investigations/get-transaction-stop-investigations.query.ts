import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetTransactionStopInvestigationsInputSchema = z.object({});

export type GetTransactionStopInvestigationsInput = z.infer<
  typeof GetTransactionStopInvestigationsInputSchema
>;

export const GetTransactionStopInvestigationsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetTransactionStopInvestigationsResult = z.infer<
  typeof GetTransactionStopInvestigationsOutputSchema
>;

@Injectable()
export class GetTransactionStopInvestigationsQuery {
  private readonly logger = new Logger(GetTransactionStopInvestigationsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetTransactionStopInvestigationsResult> {
    this.logger.debug({}, 'get_transaction_stop_investigations: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>(
        '/order/transactionStops/investigations',
        undefined,
      );
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_transaction_stop_investigations', result, start);
    }
  }
}
