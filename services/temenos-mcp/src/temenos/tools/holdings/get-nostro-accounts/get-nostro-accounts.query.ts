import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetNostroAccountsInputSchema = z.object({});

export type GetNostroAccountsInput = z.infer<typeof GetNostroAccountsInputSchema>;

export const GetNostroAccountsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetNostroAccountsResult = z.infer<typeof GetNostroAccountsOutputSchema>;

@Injectable()
export class GetNostroAccountsQuery {
  private readonly logger = new Logger(GetNostroAccountsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(_input: Record<string, never>): Promise<GetNostroAccountsResult> {
    this.logger.debug({}, 'get_nostro_accounts: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/accounts/nostro/', undefined);
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_nostro_accounts', result, start);
    }
  }
}
