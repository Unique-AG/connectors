import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetRepoPositionMovementsInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
  portfolioId: z.string().optional().describe("ID of the portfolio or security account"),
  instrumentId: z.string().optional().describe("Identifier of the instrument"),
  depositoryId: z.string().optional().describe("ID of the securities depository"),
});

export type GetRepoPositionMovementsInput = z.infer<typeof GetRepoPositionMovementsInputSchema>;

export const GetRepoPositionMovementsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetRepoPositionMovementsResult = z.infer<typeof GetRepoPositionMovementsOutputSchema>;

@Injectable()
export class GetRepoPositionMovementsQuery {
  private readonly logger = new Logger(GetRepoPositionMovementsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetRepoPositionMovementsInput): Promise<GetRepoPositionMovementsResult> {
    this.logger.debug({}, 'get_repo_position_movements: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/holdings/instruments/repurchaseAgreements/positionMovements', {
        recordId: input.recordId,
        portfolioId: input.portfolioId,
        instrumentId: input.instrumentId,
        depositoryId: input.depositoryId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_repo_position_movements', result, start);
    }
  }
}
