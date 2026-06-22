import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';

export const GetParticipantsInputSchema = z.object({
  recordId: z.string().optional().describe('Unique identifier of an entity'),
  accountOfficer: z.string().optional().describe('Identifier of the department account officer'),
  user: z.string().optional().describe('The user who created the record'),
});

export type GetParticipantsInput = z.infer<typeof GetParticipantsInputSchema>;

export const GetParticipantsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetParticipantsResult = z.infer<typeof GetParticipantsOutputSchema>;

@Injectable()
export class GetParticipantsQuery {
  private readonly logger = new Logger(GetParticipantsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetParticipantsInput): Promise<GetParticipantsResult> {
    this.logger.debug({}, 'get_participants: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/party/participants', {
        recordId: input.recordId,
        accountOfficer: input.accountOfficer,
        user: input.user,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_participants', result, start);
    }
  }
}
